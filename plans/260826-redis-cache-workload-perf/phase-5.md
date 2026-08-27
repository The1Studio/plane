# Phase 5 — Benchmark harness, verification, propagation

**Goal:** prove the claims with re-runnable measurements, and make the benchmark repeatable so the
next person does not rebuild it (`rules/search-before-you-build.md`).

**Depends on:** Phases 1, 3 and 4. **Serial terminal wave** — it drives one staging stack, a
single-instance resource that cannot be exercised by concurrent lanes.

**Owns:** `scripts/bench/`, `docs/FORK.md`, `CLAUDE.md`.

---

## Deliverable 1 — a committed benchmark harness

The measurements behind this plan were ad-hoc scripts copied into a container. Commit them so the
before/after is reproducible:

```
scripts/bench/
  redis_cache_bench.py     # endpoint medians, query counts, payload sizes
  redis_server_bench.sh    # valkey-benchmark + INFO capture
  README.md                # how to run against staging, and what each number means
```

`redis_cache_bench.py` must report, for each endpoint: median / min / max over N runs, query count,
SQL ms, payload KB, **and the cache hit rate for the run**. The hit rate is not decoration — without
it a fast number cannot be distinguished from a fast miss, which is precisely the trap production's
3-key "98% hit rate" fell into.

**Set `DEBUG=False`.** The original probe set `settings.DEBUG = True` to capture
`connection.queries`, which silently disabled `cache_response` writes (`plane/utils/cache.py:41`
gates on `not settings.DEBUG`) and produced a meaningless "cached endpoint that isn't cached"
reading. Capture query counts separately from timing runs, and put a comment in the harness saying
why — this is a trap that will otherwise be re-entered.

## Deliverable 2 — verification against the success criteria

Each measured, each with its failure condition named:

| #   | Criterion                                           | Fails if                                                                                                                                                                                                                                                                         |
| --- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Warm `…/workload/` median **< 10 ms**               | hit rate reported alongside is not ~100% — a fast miss must not pass                                                                                                                                                                                                             |
| 2   | Miss `…/workload/` median **< 75 ms** (caching off) | measured with cache on                                                                                                                                                                                                                                                           |
| 3   | **Staleness is zero**                               | any of Phase 3's seven models fails write-then-immediately-read                                                                                                                                                                                                                  |
| 4   | Cold-spike max **< 300 ms**                         | measured only on warm runs                                                                                                                                                                                                                                                       |
| 5   | Core db0 keys survive a db1 fill to `maxmemory`     | not actually filled to the bound                                                                                                                                                                                                                                                 |
| 6   | `SLOWLOG LEN` 0; hit rate recorded                  | recorded as an assumption rather than read. **Do not gate on `evicted_keys` or `used_memory`** — under D6 (no TTL) db1 fills to `maxmemory` and evicts continuously by design, so both are expected values, not health signals. Hit rate is the metric that can actually go bad. |
| 7   | `…/views-ext/…/issues/` improvement                 | `GroupedWorkspaceUserProfileIssuesEndpoint` was never benchmarked — measure it before claiming any result for it                                                                                                                                                                 |

### Criterion 5 in full

```bash
ssh server 'C=plane-staging-app-plane-redis-1
docker exec $C valkey-cli -n 0 DBSIZE                      # core keys before
docker exec $C valkey-benchmark -q -n 300000 -c 20 -d 8192 -t set -r 300000 --dbnum 1 >/dev/null
docker exec $C valkey-cli INFO stats | grep evicted_keys
docker exec $C valkey-cli -n 0 DBSIZE                      # core keys after — must be unchanged
docker exec $C valkey-cli -n 1 FLUSHDB'
```

A `DBSIZE` on db0 that drops means `allkeys-lru` is evicting core's keys under fork pressure, and
D5's containment assumption is wrong — report it rather than adjusting the threshold to hide it.

**Two cautions on that script.** It writes into **db1, which now holds the live fork cache**, and
its closing `FLUSHDB` therefore wipes it — acceptable on staging (every entry is recomputable, and
that premise is also what justifies disabling RDB in Phase 1) but **never run it against
production**. And under D6 the instance reaches `maxmemory` in normal operation anyway, so this
test no longer creates an artificial condition — it reproduces the steady state. That is why the
criterion is load-bearing rather than a formality: if core keys cannot survive here, they will not
survive a normal Tuesday either.

## Deliverable 3 — record the results honestly

Write a results table into `plan.md` under a new `## Measured outcome` section, including anything
that **missed** its target. A criterion that was not met is reported as not met; targets are not
revised to match what the run produced (`rules/pinned-baseline-test-companion.md` — never re-pin to
the present).

## Deliverable 4 — propagation

Per the CLAUDE.md standing rule:

- **`CLAUDE.md` § "Custom features (fork-owned)"** — add a `workload_cache/` entry: versioned-key
  response caching for the workload and views-ext endpoints, db1, zero-staleness via `INCR` on a
  per-workspace counter, model-less and endpoint-less (no migrations, no touch-point 2 entry).
- **`docs/FORK.md`** — record the db1 convention and _why_ (core's `KEYS *` is per-database, so
  separating the keyspace contains the blocking-sweep hazard without a core edit).
- **Sibling repos** — no change expected. No endpoint, field, or request/response shape is
  introduced; this is caching and optimization behind existing contracts. **If Phase 4 altered any
  response field**, that expectation is void: open issues on `plane-mcp-server`, `plane-node-sdk`
  and `plane-python-sdk` per `.claude/skills/plane-propagate/`, and never edit a sibling repo from
  this repo's PR.

## Deliverable 5 — carry the known gaps forward

State plainly, in `plan.md`, what was **not** fixed, so a future reader does not mistake silence for
absence:

- Core's blocking `KEYS` in `plane/utils/cache.py:66` — contained by D5, not fixed.
- Sessions in Postgres at 0.389 ms/request — measured, out of scope, blocked on the custom
  `device_info` column.
- No CPU/memory limit on the Valkey container — accepted given the 1 G bound and 23 G host headroom.
- `rediss://` handling in the fork client is **unverified** — this deployment is plain `redis://`.

## Success criteria

- Harness committed and runnable by someone who was not in this session, from its README alone.
- All seven criteria measured, with misses reported as misses.
- `CLAUDE.md` and `docs/FORK.md` updated in the same PR as the code.
