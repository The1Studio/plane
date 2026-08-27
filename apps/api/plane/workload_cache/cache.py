# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The only public surface of this app. Phase 3 calls these three functions and
# nothing else — it must never construct a key, touch the client, or read the
# version counter directly.
#
# Freshness model: entries are keyed by a per-workspace version counter. Any
# write bumps the counter with INCR, which makes every prior entry for that
# workspace unreachable IMMEDIATELY — including the writing user's own. That is
# what delivers zero staleness. A TTL cannot: measured write rate is ~33/hour in
# the busiest workspace, so any TTL leaves a window in which your own edit is
# invisible, and that window is exactly when someone is looking.

import json
import logging

from django.http import HttpResponse
from rest_framework.renderers import JSONRenderer

from .client import get_client
from .keys import entry_key, version_key

_renderer = JSONRenderer()

logger = logging.getLogger(__name__)


def _get_version(client, slug):
    """Current version for a workspace. A missing counter reads as 0.

    Deliberately does NOT write the counter on read: a read that writes turns
    every cache miss into a Redis write, and the counter's absence already means
    exactly what 0 means.
    """
    raw = client.get(version_key(slug))
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        # A corrupt counter must not wedge the cache permanently. Treating it
        # as 0 costs one generation of misses and self-heals on the next bump.
        logger.warning("workload_cache: non-integer version for %s — treating as 0", slug)
        return 0


def get_cached_bytes(surface, slug, user_id, params):
    """Return the cached response as pre-rendered JSON bytes, or None on a miss.

    Bytes, not a dict, and that is the point. Entries are stored as the exact
    output of DRF's JSONRenderer, so a hit can be written straight to the wire:
    no json.loads on the way out and no re-render on the way back. Measured on
    the 478 KB workload payload, round-tripping through a dict cost 6.09 ms to
    decode plus ~5 ms to re-encode — about 11 ms of pure serialization to
    convert JSON into JSON.

    Byte-identity with the miss path is by construction, not by luck: the miss
    path renders `data` with this same JSONRenderer instance before caching it,
    so a hit returns precisely the bytes that request would have produced.

    Fail-open: any Redis error is a miss, never an exception. A cache outage
    degrades the endpoint to its uncached latency (~99 ms), never to a 500.
    """
    client = get_client()
    if client is None:
        return None
    try:
        version = _get_version(client, slug)
        return client.get(entry_key(surface, slug, user_id, version, params))
    except Exception:
        logger.warning("workload_cache: read failed for %s/%s — serving uncached", surface, slug, exc_info=True)
        return None


def render_json(data):
    """Render a response body exactly as the miss path will return it."""
    return _renderer.render(data)


def set_cached(surface, slug, user_id, params, value):
    """Store a response. `value` may be pre-rendered bytes or a dict.

    Fail-open — a write failure is a no-op.

    Written with NO expiry (D6). `allkeys-lru` on the instance is the sole
    reclamation mechanism, so a superseded entry occupies memory until LRU
    evicts it. Do not add `ex=`/`px=` here: it is the reflexive thing to do when
    reviewing cache code and it would make entries expire on a schedule the
    design does not assume. tests/test_cache.py asserts TTL == -1 for exactly
    this reason.
    """
    client = get_client()
    if client is None:
        return
    try:
        version = _get_version(client, slug)
        client.set(
            entry_key(surface, slug, user_id, version, params),
            value if isinstance(value, (bytes, bytearray)) else render_json(value),
        )
    except Exception:
        logger.warning("workload_cache: write failed for %s/%s — continuing", surface, slug, exc_info=True)


def bump_workspace(slug):
    """Invalidate every cached response for a workspace. O(1), no key scanning.

    FAIL-LOUD, unlike every other function here. A swallowed bump means a
    subsequent read serves stale data while the write appears to have
    succeeded — a timeline that keeps showing the old value after you edited it.
    That is strictly worse than surfacing the error, so this one propagates.
    """
    client = get_client()
    if client is None:
        # No client at all means nothing was ever cached, so there is nothing
        # stale to serve. This is not the swallowed-error case above.
        return
    client.incr(version_key(slug))


class CachedJSONResponse(HttpResponse):
    """A JSON response carrying pre-rendered bytes, with `.data` still available.

    Returning a bare HttpResponse was faster but broke the DRF contract that
    in-process callers rely on — `response.data` raised AttributeError, which
    is how 18 views_ext tests caught it. The bytes ARE the point (they avoid
    decoding a payload only to re-encode it), so the fix is to keep them and
    decode lazily: a real HTTP client never touches `.data`, so it costs
    nothing on the wire path, while tests and any direct caller still work.
    """

    def __init__(self, body, status=None):
        super().__init__(body, content_type="application/json", status=status)
        self._raw_body = body

    @property
    def data(self):
        return json.loads(self._raw_body)
