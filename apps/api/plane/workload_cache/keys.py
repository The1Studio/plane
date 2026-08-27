# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Cache key construction. The shape here is the contract Phase 3 codes against
# (plans/260826-redis-cache-workload-perf/references/cache-contract.md) — do not
# change a segment without changing that file in the same commit.

import hashlib

NAMESPACE = "wlc"

# Fixed surface identifiers. Never free-form: a typo'd surface would silently
# create a parallel keyspace that no invalidation ever reaches.
SURFACE_WORKLOAD = "workload"
SURFACE_VIEWSEXT = "viewsext"
VALID_SURFACES = frozenset({SURFACE_WORKLOAD, SURFACE_VIEWSEXT})

# How each surface decides which params enter the hash.
#
# Two modes, and picking the wrong one is a CORRECTNESS bug, not a performance
# one:
#
#   tuple -> closed allow-list. Only these params are hashed; anything else is
#            EXCLUDED. Safe ONLY where the endpoint's parameter surface is
#            itself closed and validated, so no unlisted param can change the
#            response. Excluding a param that DOES change the response makes two
#            different responses collide on one key — the cache then serves the
#            WRONG data, not merely a miss.
#
#   None  -> hash the entire normalized query string. Required where the
#            parameter surface is OPEN. Costs some key fragmentation from
#            tracking/cache-buster args; a wasted entry is cheap, a collision is
#            wrong.
#
# workload: CLOSED. _parse_common() returns a fixed validated dict and 400s
# anything malformed, so the allow-list below is the entire surface. The names
# are that PARSED dict's keys, not raw query args — hashing parsed values means
# requests differing only in formatting ("2026-8-1" vs "2026-08-01",
# project_ids in a different order) share one entry instead of minting two
# identical payloads.
#
# views_ext: OPEN. The endpoint feeds request.query_params through
# issue_filters() and a ComplexFilterBackend filterset, both accepting a wide,
# independently-evolving set of names. An allow-list would go stale the moment
# core adds a filter — and would do so silently, serving one filter's results
# under another's key.
RESPONSE_AFFECTING_PARAMS = {
    SURFACE_WORKLOAD: (
        "granularity",
        "date_from",
        "date_to",
        "requested_project_ids",
        "assignee_ids",
        "state_groups",
        "route_project_id",
    ),
    SURFACE_VIEWSEXT: None,
}


def _normalize(value):
    """Collapse a param value to a stable string.

    A list is sorted, so `?project=a&project=b` and `?project=b&project=a`
    produce the same key — they produce the same response.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(sorted(str(v) for v in value))
    return str(value)


def params_hash(surface, params):
    """Stable hash over the params that can change the response.

    See RESPONSE_AFFECTING_PARAMS for the two modes and when each is safe.
    `params` may be a plain dict or a QueryDict.
    """
    allowed = RESPONSE_AFFECTING_PARAMS.get(surface, ())
    if allowed is None:
        allowed = sorted(params.keys())

    pairs = []
    for name in sorted(allowed):
        if name not in params:
            continue
        if hasattr(params, "getlist"):
            raw = params.getlist(name)
            raw = raw[0] if len(raw) == 1 else raw
        else:
            raw = params.get(name)
        normalized = _normalize(raw)
        if normalized == "":
            # Empty is indistinguishable from absent for every param on these
            # surfaces, so treat them alike rather than minting two keys for one
            # response.
            continue
        pairs.append(f"{name}={normalized}")
    return hashlib.sha1("&".join(pairs).encode("utf-8")).hexdigest()[:16]


def version_key(slug):
    """Key holding a workspace's version counter."""
    return f"{NAMESPACE}:ver:{slug}"


def entry_key(surface, slug, user_id, version, params):
    """Key for one cached response.

    `user_id` is part of the key because these responses are permission-scoped:
    a guest restricted to one project must never be served a full member's row
    set. Dropping this segment would be a data-exposure bug, not an
    optimization.
    """
    if surface not in VALID_SURFACES:
        raise ValueError(f"unknown cache surface: {surface!r}")
    return f"{NAMESPACE}:v{version}:{surface}:{slug}:{user_id}:{params_hash(surface, params)}"
