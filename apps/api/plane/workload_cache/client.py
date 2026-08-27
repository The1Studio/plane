# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Redis client for the fork's response cache. Deliberately NOT a Django CACHES
# alias: adding one would mean editing settings/common.py beyond INSTALLED_APPS,
# which is outside the 7 sanctioned fork touch-points (docs/FORK.md).
#
# The client targets **db1**, while core's django_redis cache stays on db0.
# That split is load-bearing, not cosmetic: core's
# invalidate_cache(..., multiple=True) issues a blocking KEYS sweep
# (plane/utils/cache.py), and KEYS is scoped per-database. Keeping fork keys
# off db0 means core's sweeps never traverse them, however large this keyspace
# grows. Measured 2026-08-26: KEYS over 20k keys stalls the server 21.1 ms.

import logging
from urllib.parse import urlparse, urlunparse

from django.conf import settings

logger = logging.getLogger(__name__)

# Fork response cache lives here; core's django_redis cache uses db0.
FORK_CACHE_DB = 1

_client = None
_client_built = False


def _build_url(redis_url, db=FORK_CACHE_DB):
    """Return `redis_url` with its database index replaced by `db`.

    REDIS_URL in this deployment is `redis://plane-redis:6379/` — no index
    present — but the community compose default and a hand-edited plane.env can
    both carry one, so handle both rather than assuming the local shape.
    """
    parsed = urlparse(redis_url)
    return urlunparse(parsed._replace(path=f"/{db}"))


def get_client():
    """Return the db1 Redis client, or None if one cannot be built.

    Never raises. A None return is what makes every caller degrade to a cache
    miss rather than a 500 — see cache.py's failure posture.
    """
    global _client, _client_built
    if _client_built:
        return _client

    _client_built = True
    redis_url = getattr(settings, "REDIS_URL", None)
    if not redis_url:
        logger.warning("workload_cache: REDIS_URL unset — response cache disabled")
        _client = None
        return None

    try:
        import redis

        kwargs = {}
        if redis_url.startswith("rediss://"):
            # Mirrors settings/common.py:246 for the SSL case. UNVERIFIED in
            # this deployment: staging and production are both plain redis://,
            # so this branch has never executed here. Do not read its presence
            # as evidence it works.
            kwargs["ssl_cert_reqs"] = None

        _client = redis.Redis.from_url(
            _build_url(redis_url),
            socket_timeout=1,
            socket_connect_timeout=1,
            **kwargs,
        )
    except Exception:
        logger.exception("workload_cache: could not build Redis client — cache disabled")
        _client = None

    return _client


def reset_client():
    """Drop the memoized client. Tests only."""
    global _client, _client_built
    _client = None
    _client_built = False
