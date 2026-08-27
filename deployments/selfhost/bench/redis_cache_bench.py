# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Benchmark harness for the fork's response cache (plane/workload_cache).
# Run it inside an api container:
#
#     docker exec <api-container> sh -c "cd /code && python manage.py shell" < redis_cache_bench.py
#
# See README.md for the full invocation and what each number means.
#
# ── THE TRAP THIS HARNESS EXISTS TO AVOID ─────────────────────────────────────
# `settings.DEBUG = True` is the obvious way to capture connection.queries, and
# it SILENTLY DISABLES cache writes: plane/utils/cache.py gates cache_response's
# cache.set on `not settings.DEBUG`. A first attempt at this measurement did
# exactly that and produced a "cached endpoint that isn't caching" reading that
# was pure artifact. Timing runs here therefore keep DEBUG=False, and query
# counts are captured in a SEPARATE pass. Do not merge the two loops.
#
# ── AND THE ONE THIS HARNESS EXISTS TO REPORT ─────────────────────────────────
# A fast number is meaningless without the hit rate beside it. Production once
# showed a 98% hit rate over THREE keys — true, and evidence of nothing. Every
# row below reports hits/misses for the run so a fast MISS cannot be mistaken
# for a working cache.

import time
from datetime import date

from django.conf import settings
from django.db import connection, reset_queries
from django.test import Client
from plane.db.models import Workspace, WorkspaceMember
from plane.workload_cache.cache import bump_workspace
from plane.workload_cache.client import FORK_CACHE_DB, get_client

RUNS = 9


def _pick_workspace():
    """Busiest workspace by project count — the worst case, not a convenient one."""
    best, best_n = None, -1
    for ws in Workspace.objects.all():
        from plane.db.models import Project

        n = Project.objects.filter(workspace=ws).count()
        if n > best_n:
            best, best_n = ws, n
    return best, best_n


def _client_for(ws):
    member = WorkspaceMember.objects.filter(
        workspace=ws, is_active=True, member__is_bot=False
    ).first()
    if member is None:
        raise SystemExit(f"no active non-bot member in workspace {ws.slug}")
    c = Client()
    c.force_login(member.member)
    return c, member.member


def _keyspace_stats(redis):
    if redis is None:
        return None
    info = redis.info("stats")
    return info.get("keyspace_hits", 0), info.get("keyspace_misses", 0)


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2]


def bench(label, client, url, ws_slug, redis):
    """One endpoint: cold miss, then RUNS warm reads, with hit-rate evidence."""
    bump_workspace(ws_slug)  # guarantee a cold start rather than assuming one
    client.get(url)  # discard: first request pays import/connection warmup
    bump_workspace(ws_slug)

    before = _keyspace_stats(redis)
    t = time.perf_counter()
    r_miss = client.get(url)
    miss_ms = (time.perf_counter() - t) * 1000

    warm = []
    for _ in range(RUNS):
        t = time.perf_counter()
        r_hit = client.get(url)
        warm.append((time.perf_counter() - t) * 1000)
    after = _keyspace_stats(redis)

    hits = misses = "n/a"
    if before and after:
        hits, misses = after[0] - before[0], after[1] - before[1]

    identical = r_miss.content == r_hit.content
    print(
        f"  {label:34s} miss {miss_ms:8.1f} ms | warm median {_median(warm):7.2f} ms "
        f"(min {min(warm):6.2f} max {max(warm):7.2f}) | {len(r_hit.content) / 1024:6.0f} KB "
        f"| hits {hits} misses {misses} | identical {identical} | HTTP {r_hit.status_code}"
    )
    if r_hit.status_code != 200:
        # An error response is small and fast, so it renders as the best row in
        # the table while measuring nothing. Say so loudly rather than letting a
        # reader skim past a 400 that looks like a 2 ms win.
        print(
            f"    *** HTTP {r_hit.status_code} — this row measures an ERROR PATH, not the endpoint. "
            f"Body: {r_hit.content[:160]!r}"
        )
    if not identical:
        print("    *** hit and miss bodies DIFFER — investigate before trusting any number above")
    return _median(warm), miss_ms


def query_profile(label, fn):
    """Query count + cursor time, in a SEPARATE pass from timing (see header).

    NOTE: cursor time is NOT the endpoint's SQL cost. It excludes ORM row
    materialization, which is most of it — measured 40 ms cursor against ~58 ms
    of actual materialization on the workload endpoint. Do not scope
    optimization work from this number alone; profile instead.
    """
    settings.DEBUG = True
    try:
        reset_queries()
        fn()
        n = len(connection.queries)
        ms = sum(float(q["time"]) for q in connection.queries) * 1000
        print(f"  {label:34s} {n:3d} queries | {ms:6.1f} ms cursor time (EXCLUDES row materialization)")
    finally:
        settings.DEBUG = False


def main():
    ws, nproj = _pick_workspace()
    client, user = _client_for(ws)
    try:
        redis = get_client()
        redis.ping()
    except Exception:  # noqa: BLE001 - a probe: ANY failure here means "no hit rates", not a crash
        redis = None
        print("!! fork cache client unreachable — hit rates will read n/a")

    from plane.db.models import Issue

    print(f"workspace={ws.slug} projects={nproj} issues={Issue.objects.filter(workspace=ws).count()}")
    print(f"fork cache db={FORK_CACHE_DB}  runs={RUNS}  DEBUG={settings.DEBUG}\n")

    wl = f"/api/workspaces/{ws.slug}/workload/"
    vx = f"/api/views-ext/workspaces/{ws.slug}/issues/"
    cases = [
        ("workload week/90d", f"{wl}?granularity=week&date_from=2026-08-01&date_to=2026-10-31"),
        ("workload day/30d", f"{wl}?granularity=day&date_from=2026-08-01&date_to=2026-08-30"),
        ("workload month/365d", f"{wl}?granularity=month&date_from=2026-01-01&date_to=2026-12-31"),
        ("views_ext ungrouped", f"{vx}?per_page=100"),
        # `state_id`, not `state` — the latter is not in ALLOWED_GROUP_BY_FIELDS and
        # 400s. A 400 row renders as a very fast 2.6 ms / 0 KB, which is exactly the
        # false-green this harness must not hand you; hence the loud check below.
        ("views_ext group_by=state_id", f"{vx}?group_by=state_id&per_page=100"),
        # search is deliberately NOT cached (high-cardinality free text), so this
        # row should show warm ~= miss. A warm number here matching the cached
        # rows means the search bypass has broken.
        ("views_ext +search (uncached)", f"{vx}?per_page=100&search=fix"),
    ]
    print("=== endpoints ===")
    for label, url in cases:
        bench(label, client, url, ws.slug, redis)

    print("\n=== query profile (separate pass, DEBUG toggled) ===")
    from plane.workload.service import compute_workload

    query_profile(
        "compute_workload week/90d",
        lambda: compute_workload(
            user=user,
            slug=ws.slug,
            granularity="week",
            date_from=date(2026, 8, 1),
            date_to=date(2026, 10, 31),
        ),
    )

    if redis is not None:
        print("\n=== cache instance ===")
        for k in ("maxmemory", "maxmemory-policy", "save", "appendonly"):
            print(f"  {k:20s} {redis.config_get(k)[k]!r}")
        ks = redis.info("keyspace")
        print(f"  {'keyspace':20s} db0={ks.get('db0')} db1={ks.get('db1')}")
        st = redis.info("stats")
        print(f"  {'evicted_keys':20s} {st.get('evicted_keys')}   (expected to climb: no TTL, LRU is the only reclamation)")
        print(f"  {'slowlog len':20s} {redis.execute_command('SLOWLOG', 'LEN')}")
        mem = redis.info("memory")
        print(f"  {'used_memory':20s} {mem.get('used_memory_human')}   (expected to sit near maxmemory once warm — NOT an incident)")


main()
