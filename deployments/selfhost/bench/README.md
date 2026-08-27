# Cache benchmarks

Two scripts, answering two different questions. Reach for the right one — the
first time this was measured, the obvious question turned out to be the wrong
one.

| Script                  | Question                                                                                                 |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| `redis_cache_bench.py`  | **Are the endpoints fast, and is the cache actually being hit?** This is almost always the one you want. |
| `redis-server-bench.sh` | Is the cache _server_ a bottleneck, and is it configured as a cache?                                     |

## Running them

Both drive a live stack over SSH; neither needs a checkout on the server.

These live beside `deploy.sh` rather than under a top-level `scripts/` because
`scripts/` is gitignored in this repo — an untracked benchmark is a benchmark
nobody else can run.

```bash
# endpoints — run inside an api container
scp deployments/selfhost/bench/redis_cache_bench.py server:/tmp/
ssh server 'docker cp /tmp/redis_cache_bench.py plane-staging-app-api-1:/tmp/ \
  && docker exec plane-staging-app-api-1 sh -c "cd /code && python manage.py shell < /tmp/redis_cache_bench.py"'

# server capacity + config — runs on the host
scp deployments/selfhost/bench/redis-server-bench.sh server:/tmp/
ssh server 'bash /tmp/redis-server-bench.sh plane-staging-app-plane-redis-1'
```

Point them at `plane-fork-app-*` instead of `plane-staging-app-*` for production.
`redis-server-bench.sh` briefly lowers `maxmemory` to prove eviction and restores
it — read that section before running it against production.

## Reading the output

**Every endpoint row reports its hit rate. That is not decoration.** Production
once showed a 98% hit rate — over _three keys_. The figure was true and told you
nothing about whether anything expensive was cached, because nothing was. A warm
median means something only next to the hits/misses for that run: a fast number
with `misses` climbing is a fast _miss path_, not a working cache.

**`identical` compares the miss body to the hit body.** They must match
byte-for-byte. If that ever reads `False`, stop and investigate before trusting
any timing above it — clients would be seeing two different payloads for one URL
depending on cache state.

**The `views_ext +search` row should show warm ≈ miss.** Free-text search is
deliberately not cached (high cardinality; every entry read once). If that row
starts looking like the cached rows, the search bypass has broken.

**Cursor time is not SQL cost.** The query-profile section reports
`connection.queries` timing, which measures only cursor execute time and
_excludes ORM row materialization_. On the workload endpoint that gap is large —
40 ms cursor against ~58 ms of actual materialization. Scoping optimization work
from this number is how a phase ends up optimizing the wrong half; profile
instead. (It did, once. See `plans/260826-redis-cache-workload-perf/phase-4.md`.)

**`used_memory` near `maxmemory` is the steady state, not an incident.** Fork
cache entries carry no TTL by design, so `allkeys-lru` is their only reclamation
path: the instance fills and stays full, and `evicted_keys` climbs continuously.
Neither is a health signal. The hit rate is the metric that can actually go bad.

## The trap baked into `redis_cache_bench.py`

`settings.DEBUG = True` is the obvious way to capture `connection.queries`, and
it **silently disables cache writes** — `plane/utils/cache.py` gates
`cache_response`'s `cache.set` on `not settings.DEBUG`. The first attempt at
this measurement did exactly that and produced a "cached endpoint that isn't
caching" reading that was pure artifact.

So timing runs keep `DEBUG=False` and query counts are captured in a separate
pass. **Do not merge those two loops.**

## What these measured

Staging, workspace `cocos` (57 projects, 6,906 issues), 2026-08-27:

|                         |                                     |
| ----------------------- | ----------------------------------- |
| `…/workload/`           | 98.8 ms → **3.42 ms** warm (478 KB) |
| `…/views-ext/…/issues/` | 67.4 ms → **2.74 ms** warm (81 KB)  |
| miss path after Phase 4 | 93 ms, 11 queries (was 13)          |
| server capacity         | 212k ops/sec, p50 0.111 ms          |
| actual load             | 0.6–6 ops/sec                       |

That last pair is the point of keeping both scripts: the server has four orders
of magnitude of headroom, and never was the problem.

Full context, decisions, and the things that turned out wrong:
`plans/260826-redis-cache-workload-perf/`.
