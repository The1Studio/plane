# Redis/Valkey cache — benchmark findings and workload-endpoint performance work

Make the two fork-owned hot endpoints fast **without introducing staleness**, and fix the two cache
configuration hazards that adding caching would otherwise activate.

**Created:** 2026-08-26
**Mode:** default (benchmark → plan → validate)
**Branch:** `staging`
**Plane:** [PLANE-188](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/67603ea6-696d-4720-99a7-16eed1cbf369) — Todo, 32 h estimated
**Cook handoff:** `/t1k:cook plans/260826-redis-cache-workload-perf/`

---

## Verified starting state

Every number below was measured on the live `server` host on 2026-08-26 against the running
`plane-staging-app-*` stack. Nothing here is recalled or estimated. Commands are reproduced so each
row is re-runnable.

### The cache server is not a bottleneck

| Fact                       | Value                                                         | Source                                 |
| -------------------------- | ------------------------------------------------------------- | -------------------------------------- |
| Image                      | `valkey/valkey:7.2.11-alpine` (reports `redis_version:7.2.4`) | `docker exec … valkey-cli INFO server` |
| Throughput SET / GET       | **211,864 / 221,729 ops/sec**, p50 **0.111 ms**               | `valkey-benchmark -q -n 100000 -c 50`  |
| Throughput pipelined (P16) | **1,923,076 / 2,040,816 ops/sec**                             | `valkey-benchmark … -P 16`             |
| Throughput @ 1 KB values   | 212,765 / 214,592 ops/sec — no degradation                    | `valkey-benchmark … -d 1024`           |
| Intrinsic latency          | 0.029 µs avg                                                  | `valkey-cli --intrinsic-latency 5`     |
| Container limits           | **none** — `NanoCpus=0 Memory=0 CpuShares=0`                  | `docker inspect`                       |

### …because it is almost entirely unused

| Fact                        | Staging | **Production (25 h real traffic)** |
| --------------------------- | ------- | ---------------------------------- |
| Keys in db0                 | 1       | **3**                              |
| `used_memory_human`         | 1.10 M  | 1.10 M                             |
| Commands processed          | 100     | 56,000 (**0.6 ops/sec**)           |
| `instantaneous_ops_per_sec` | 6       | 0                                  |
| `keyspace_hits` / `misses`  | 18 / 15 | 35,092 / 728                       |
| `evicted_keys`              | 0       | 0                                  |
| `SLOWLOG LEN`               | —       | **0**                              |

> **The production "98% hit rate" proves nothing.** It is computed over **three keys** — the sampled
> key is `:1:/api/instances/`, re-read on every page load. A hit rate over a 3-key keyspace is not
> evidence that anything expensive is cached. It is not, and the next table is why.

### Only 5 endpoints in the entire API are cached, and none of them are expensive

`@cache_response` appears on exactly five call sites (`grep -rn "cache_response" plane/`):
`workspace/label.py`, `workspace/estimate.py`, `license/api/views/instance.py`,
`license/api/views/configuration.py`, `license/api/views/admin.py`.

**`plane/workload/` and `plane/views_ext/` contain zero cache calls** — verified by
`grep -rn "cache" plane/workload/ plane/views_ext/`, which returns nothing. Scope of that search:
both fork app trees in full, excluding `__pycache__`.

### What is actually expensive

Measured through the full HTTP stack (`django.test.Client`, `force_login`, `DEBUG=False`), median
of 5 runs, workspace `cocos` (57 projects, 6,906 issues — staging holds a production clone):

| Endpoint                                                | Cached | Median      | Min  | Max        | Payload |
| ------------------------------------------------------- | ------ | ----------- | ---- | ---------- | ------- |
| `GET /api/workspaces/:slug/workload/`                   | **no** | **98.8 ms** | 97.1 | **1147.0** | 478 KB  |
| `GET /api/views-ext/workspaces/:slug/issues/`           | **no** | **67.4 ms** | 66.5 | 127.3      | 81 KB   |
| `GET /api/workspaces/:slug/labels/`                     | yes    | 2.7 ms      | 2.6  | 2.9        | 5 KB    |
| `GET /api/workspaces/:slug/labels/` (cold, after flush) | —      | 6.7 ms      | —    | —          | 5 KB    |

The cached core endpoint is the control: the mechanism works (6.7 → 2.7 ms), it is simply not
applied anywhere that costs real time.

### The measured win, on the real payload

Pickle is not free, so this was measured on the actual 520 KB workload response object rather than
assumed:

| Operation                                      | Cost                         |
| ---------------------------------------------- | ---------------------------- |
| `cache.get` — real 520 KB workload payload     | **2.06 ms**                  |
| `cache.set` — same                             | 1.72 ms                      |
| Stored size in Valkey                          | 320 KB                       |
| **Recompute via DB**                           | **92.9 ms**                  |
| **Speedup on a hit**                           | **≈45×**                     |
| API container → cache round-trip (small value) | 0.072 ms GET / 0.040 ms PING |

### Where the 99 ms actually goes — a correction

`compute_workload` issues **13 queries totalling 38.0 ms of SQL**. Wall time is ~99 ms, so
**~61 ms (62%) is Python aggregation and DRF serialization of the 478 KB payload, not SQL.**

| #   | ms    | Table                | Note                      |
| --- | ----- | -------------------- | ------------------------- |
| 12  | 15.00 | `issue_assignees`    | largest single query      |
| 10  | 6.00  | `issues`             | main row fetch            |
| 8   | 5.00  | `issues`             | `COUNT(*)` cap check      |
| 9   | 5.00  | `workload_estimates` | main estimate fetch       |
| 7   | 4.00  | `workload_estimates` | `COUNT(*)` cap check      |
| 6   | 1.00  | `project_members`    | near-duplicate of #2      |
| 11  | 1.00  | `workload_estimates` | `COUNT(*)` cap check      |
| 13  | 1.00  | `project_members`    | roster                    |
| 1–5 | ~0    | mixed                | #5 duplicates #1 verbatim |

This matters for scoping: **query tuning alone cannot reach a ~50 ms miss path.** Phase 4 targets
both halves and states its own realistic ceiling rather than inheriting an optimistic figure.

### Write rate — how often a cache entry would be invalidated

`updated_at` on the cloned production data is genuine production activity. Staging itself receives
no traffic, which is why the "last 1 h" buckets read zero; the 7-day rates are the real signal.

| Scope             | Invalidating writes                                               |
| ----------------- | ----------------------------------------------------------------- |
| `cocos` (busiest) | 11.29 estimates/h + 22.31 issues/h = **~33/h → one every ~110 s** |
| All workspaces    | 3,206 estimates + 6,600 issues over 7 d = **~58/h**               |

**Why this rules out TTL.** At one write every ~110 s a 60 s TTL is not much _staler_ on average
than event-driven invalidation — but averages are not the requirement. The requirement is that
**your own edit is visible immediately**; another user's may lag a moment. No TTL value delivers
that. Versioned keys do, at O(1).

### Two hazards that adding caching would activate

1. **`maxmemory=0` with `maxmemory-policy=noeviction`.** Inert at 1.1 MB. Once ~320 KB blobs are
   cached per (workspace × user × granularity × range), Valkey will begin **returning errors on
   writes instead of evicting** — a cache that breaks the application when it fills.
2. **`invalidate_cache(..., multiple=True)` runs a blocking `KEYS`.** `plane/utils/cache.py:66`
   calls `cache.delete_many(keys=cache.keys(f"*{key}*"))`; django-redis's `keys()` issues `KEYS`,
   which is O(N) and stalls the single-threaded server. Measured over a synthetic 20,000-key
   keyspace: **`KEYS` 21.1 ms (blocking) vs `SCAN` 25.6 ms (non-blocking)**. At 3 keys this is
   invisible; it grows linearly with exactly the keyspace this plan adds.

### Lower-priority findings, recorded but not scheduled

- RDB persistence is on (`save 3600 1 300 100 60 10000`) for a pure cache — a periodic background
  fork and disk write nothing depends on. Addressed in Phase 1.
- `SESSION_ENGINE = "plane.db.models.session"` — sessions are in Postgres at **0.389 ms per
  authenticated request**. Real but small, and the model carries a custom `device_info` column that
  a naive move to Redis would break. **Not in scope**; recorded for a future decision.
- `mem_fragmentation_ratio: 12.47` is **not** a finding. It is 1.10 MB live against 13.25 MB
  baseline RSS on an almost-empty instance, not fragmentation. Do not act on it.
- The Valkey container has no CPU or memory limit. Given 23 G available on the host and a 1 G cache
  bound, this is acceptable; noted so it is a decision rather than an oversight.

---

## Decisions (resolved with the user 2026-08-26)

| #   | Decision                       | Resolution                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Caching scope                  | **Fork-owned endpoints only** — `plane/workload/` and `plane/views_ext/`. No core files edited, fork-rebase discipline untouched.                                                                                                                                                                                                                                                                                                                                                   |
| D2  | Freshness strategy             | **Per-workspace versioned keys AND miss-path query/serialization optimization.** Zero staleness including the editor's own writes; the miss path gets faster too, which also addresses the 1147 ms cold spike.                                                                                                                                                                                                                                                                      |
| D3  | Memory bound                   | **`maxmemory 1gb` + `maxmemory-policy allkeys-lru`** on the cache instance.                                                                                                                                                                                                                                                                                                                                                                                                         |
| D4  | RDB persistence                | **Disabled on staging _and_ production** (`save ""`).                                                                                                                                                                                                                                                                                                                                                                                                                               |
| D5  | Fork cache keyspace            | **Redis db1**, separate from core's db0. See below.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| D6  | Entry expiry                   | **None — no TTL.** `allkeys-lru` is the sole reclamation mechanism. Freshness was never the TTL's job (the version bump owns it), so removing it costs nothing on staleness and keeps a quiet workspace warm indefinitely. It does change the steady state: db1 fills to `maxmemory` and stays there, `evicted_keys` climbs continuously, and both are expected rather than incidents. See the D5 caveat below — this makes core-key survival load-bearing rather than theoretical. |
| D7  | `views_ext` in-process `.data` | Cached responses expose JSON types (a `date` becomes its ISO string). HTTP body byte-identical; no production caller affected. See below.                                                                                                                                                                                                                                                                                                                                           |

### D5 — fork caches live on a separate Redis DB index

Proposed by the plan rather than handed down, and **confirmed by the user 2026-08-26** alongside
D6. It is close to the only way to honour D1 and neutralise hazard 2 at once.

`KEYS` is scoped **per database**. Core's `invalidate_cache(multiple=True)` runs `KEYS *…*` against
db0. If fork caching also wrote to db0, every core invalidation would begin scanning our thousands
of keys — the hazard would land on core paths we did not touch and cannot fix without a core edit.

So the fork cache client connects to **db1**, built inside the fork app from `REDIS_URL`, with no
`CACHES` change and therefore no `settings/common.py` edit. Core keeps db0 and its `KEYS` sweeps
never see our keyspace.

Two consequences to hold in mind, neither blocking:

- `maxmemory` is **instance-wide**, not per-db, and **D6 (no TTL) sharpens this**. An earlier
  revision of this bullet said a db1 fill was "not a live risk" because core uses 1.1 MB against a
  1 G bound. That reasoning assumed entries expired on their own. They do not: with no TTL, db1
  reaches `maxmemory` and **stays** there, so core's db0 keys compete for eviction _permanently_
  rather than during occasional spikes. Core's 3 keys are read on essentially every page load and
  LRU should always rank them hot — but this is now the assumption the design leans on, not a
  footnote. Phase 5 verifies it under a real fill.
- The core `KEYS` hazard is **contained, not fixed**. It remains in `plane/utils/cache.py` for core
  endpoints. Recorded as a known gap; fixing it is a core edit and out of D1's scope.

---

## Phases

| Phase           | Goal                                                       | File ownership                                | Depends on |
| --------------- | ---------------------------------------------------------- | --------------------------------------------- | ---------- |
| [1](phase-1.md) | Cache instance hardening — memory bound, eviction, RDB off | `deployments/selfhost/`, host config          | —          |
| [2](phase-2.md) | Versioned-key cache layer in a fork app                    | `plane/workload_cache/` (new)                 | —          |
| [3](phase-3.md) | Wire workload + views_ext endpoints and version-bump hooks | `plane/workload/`, `plane/views_ext/`         | 2          |
| [4](phase-4.md) | Miss-path optimization — queries and serialization         | `plane/workload/service.py`, `aggregation.py` | —          |
| [5](phase-5.md) | Benchmark harness, verification, propagation               | `deployments/selfhost/bench/`, `docs/`        | 1,3,4      |

Phases **1, 2 and 4 are mutually independent** and may run in parallel — disjoint file sets, no
shared declarations. Phase 3 consumes the module Phase 2 declares, so the cache-key format and the
bump interface are **hoisted into Phase 2 and pinned there** (`references/cache-contract.md`) rather
than being invented by either side. Phase 5 is a serial terminal wave: it verifies against one
staging stack, which is a single-instance resource and cannot be exercised concurrently.

---

## Risk Assessment

| Risk                                                                   | L (1-5) | I (1-5) | Score  | Mitigation                                                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------------------- | ------- | ------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Version bump missed on some write path → stale timeline shown as fresh | 3       | 5       | **15** | Bump via `post_save`/`post_delete` signals on `Issue`, `IssueAssignee`, `WorkloadEstimate` rather than per-endpoint calls, so core-owned write paths are covered too. Phase 5 asserts staleness is zero by writing then immediately re-reading.                                                                                                           |
| `allkeys-lru` evicts core db0 keys under a db1 fill                    | 3       | 3       | 9      | Raised from 2 by D6: with no TTL, db1 sits at `maxmemory` permanently, so this is the steady state rather than a spike. Core's 3 keys are read on every page load and should stay LRU-hot. Phase 5 fills db1 to the bound and asserts db0 `DBSIZE` is unchanged; a drop means the containment assumption is wrong and must be reported, not tuned around. |
| Cached payload memory growth larger than modelled                      | 1       | 2       | 2      | 320 KB measured per entry; `maxmemory` makes overrun an eviction, not an outage. Lowered by D6: unbounded growth is now the _expected_ steady state, so there is little left to be surprised by. `used_memory` is no longer a meaningful signal and Phase 5 reports hit rate instead.                                                                     |
| Query optimization changes aggregation results                         | 2       | 5       | 10     | Phase 4 pins current output as a golden fixture **before** touching the query path; any diff fails.                                                                                                                                                                                                                                                       |
| Disabling RDB on production is applied without a staging soak          | 2       | 2       | 4      | Phase 1 lands staging first and verifies, then production in the same phase but as a separate step.                                                                                                                                                                                                                                                       |
| Cache hit rate disappoints because view:write ratio is low             | 3       | 2       | 6      | Phase 5 measures the real hit rate rather than asserting one. Phase 4's miss-path work is what makes a low hit rate acceptable rather than a failure.                                                                                                                                                                                                     |

No risk scores ≥ 15 other than the invalidation-coverage risk, which is mitigated at the signal
layer rather than the endpoint layer specifically to close it.

## Timeline

| Phase                                | Effort   | Notes                                                  |
| ------------------------------------ | -------- | ------------------------------------------------------ |
| 1 — Cache instance hardening         | 3 h      | Config only; no code paths change                      |
| 2 — Versioned-key cache layer        | 6 h      | New fork app, contract file, unit tests                |
| 3 — Endpoint wiring + signals        | 8 h      | Highest-risk phase; signal coverage is the crux        |
| 4 — Miss-path optimization           | 10 h     | Golden fixture first, then queries, then serialization |
| 5 — Benchmark harness + verification | 5 h      | Serial; single staging stack                           |
| **Total**                            | **32 h** | Critical path: 2 → 3 → 5 (19 h); 1 and 4 run alongside |

## Success criteria

Every one is a measurement, not an assertion, and each names what would make it fail:

1. `GET …/workload/` warm-cache median **< 10 ms** (from 98.8 ms). Fails if the cache is not being
   hit — Phase 5 reports hit rate alongside, so a fast-looking miss cannot pass.
2. `GET …/workload/` **miss-path** median **< 75 ms** (from 98.8 ms). Deliberately not "50 ms": SQL
   is only 38 ms of the total, so a 50 ms target would require eliminating serialization entirely.
   Revise upward only with a measurement, never to match whatever the run reported.
3. **Staleness is zero.** Write an estimate, immediately re-read the timeline, assert the new value
   is present. Fails if any write path lacks a version bump.
4. Cold-spike max drops below 300 ms (from 1147 ms).
5. Core db0 keys survive a db1 fill to `maxmemory`.
6. `SLOWLOG LEN` stays 0 and `evicted_keys` behaviour is recorded, not assumed.

## Measured outcome (2026-08-27, Phases 1–3)

Measured in a throwaway container built from `makeplane/plane-backend:staging` with the change
mounted, on the staging network against the staging database — the live staging stack was not
modified. Workspace `cocos` (57 projects, 6,906 issues), median of 9 runs.

| Criterion                    | Target     | Measured                         |                                    |
| ---------------------------- | ---------- | -------------------------------- | ---------------------------------- |
| Warm `…/workload/`           | < 10 ms    | **3.30 ms** (min 3.12, max 4.02) | met                                |
| Warm `…/views-ext/…/issues/` | —          | **2.74 ms** (min 2.56, max 3.43) | met                                |
| Affected test suites         | 0 failures | **301 passed, 0 failed**         | met                                |
| Miss `…/workload/`           | < 75 ms    | **97.5 ms**                      | **NOT met — Phase 4 not yet done** |
| Staleness                    | zero       | **zero**, evidence below         | met                                |
| Hit byte-identical to miss   | required   | **True**, both endpoints         | met                                |
| Entry expiry                 | none (D6)  | `TTL == -1`, `expires: 0` on db1 | met                                |

`…/workload/` went 98.8 ms → **3.30 ms warm, a 30× improvement**; `…/views-ext/…/issues/`
67.4 ms → 2.74 ms.

**The miss path is unchanged at 97.5 ms and that is expected** — Phase 4 is the phase that
addresses it and has not been implemented. Recorded as not met rather than quietly rescoped.

### Final measured state — all five phases on staging, 2026-08-27

Produced by the committed harness (`deployments/selfhost/bench/redis_cache_bench.py`) against the
deployed stack, not by an ad-hoc script.

| Endpoint                          | Miss         | **Warm**    | Payload |                    |
| --------------------------------- | ------------ | ----------- | ------- | ------------------ |
| `workload` week/90d               | 87.9 ms      | **3.39 ms** | 478 KB  | 26x                |
| `workload` day/30d                | 136.7 ms     | **3.42 ms** | 490 KB  | 40x                |
| `workload` month/365d             | 110.3 ms     | **4.04 ms** | 841 KB  | 27x                |
| `views_ext` ungrouped             | 67.4 ms      | **2.64 ms** | 81 KB   | 26x                |
| **`views_ext` group_by=state_id** | **685.4 ms** | **5.80 ms** | 1900 KB | **118x**           |
| `views_ext` +search               | 46.4 ms      | 47.62 ms    | 64 KB   | uncached by design |

Every cached row: `hits 20 misses 1`, `identical True`, HTTP 200. The `+search` row showing
warm ≈ miss with `hits 0 misses 0` is the bypass working, not a failure.

**A finding the harness surfaced that this plan never knew about.** `views_ext` with `group_by`
costs **685 ms and returns 1.9 MB** — ten times the ungrouped endpoint and by a wide margin the
slowest path measured in this whole effort. It was invisible until now because the original probe
used `group_by=state`, which is not in `ALLOWED_GROUP_BY_FIELDS` and 400s; a 400 renders as a very
fast 2.6 ms / 0 KB row, so it read as the _cheapest_ endpoint rather than the most expensive. The
harness now flags any non-200 row loudly for exactly that reason.

This is the Views tab's default grouped layout, so it is a real user-facing path — and it gets the
largest win here, 118x.

**`slowlog len: 1`** is this session's own `FLUSHDB` (67 ms clearing 112,784 keys after the
criterion-5 fill), and `evicted_keys: 112784` is that same test's cumulative count. Neither is
application behaviour; both are recorded so a future reader does not chase them.

### A regression the bytes optimization caused, and the fix

Returning a bare `HttpResponse` for pre-rendered bytes broke **18 views_ext tests** with
`AttributeError: 'HttpResponse' object has no attribute 'data'`. The failures landed precisely on
the cacheable paths — absent/empty `search` — while every search-present test, which bypasses the
cache, passed. That pattern is what identified it as the cache path rather than coincidence.

`response.data` is part of the DRF contract in-process callers rely on, so this was a real
interface break, not a test artifact. Both benefits are keepable: `CachedJSONResponse` carries the
pre-rendered bytes and decodes **lazily** in a `.data` property. A real HTTP client never touches
`.data`, so the wire path still pays nothing, while tests and direct callers work unchanged.
`TestCachedJSONResponse` pins all three properties — body bytes, `.data` correctness, and that the
decode stays lazy — so the speedup cannot be reintroduced at the interface's expense again.

### D7 — cached `views_ext` responses expose JSON types on in-process `.data`

Decided with the user 2026-08-27, under the no-side-effects gate.

Caching a _rendered_ response means in-process `response.data` is decoded from JSON rather than
held pre-render, so a `date` arrives as `'2026-06-15'` instead of `date(2026, 6, 15)`. **No caching
design avoids this** — a date cannot round-trip through JSON and return a date.

Evidence gathered before deciding: no production code reads `.data` from these endpoints
in-process (the only non-test references are `urls.py` routing and docstrings), exactly one
assertion depended on the native type, and the **HTTP body is byte-identical** — verified — so no
client sees any change. The sibling profile endpoint is uncached and unaffected.

Resolution: keep `views_ext` cached (67.4 ms -> 2.74 ms, 25x) and update that one assertion, with
the reason recorded inline at the test rather than left as a silent behaviour change.

### A finding that changed the design mid-implementation

The first working version measured **11.35 ms** warm, missing the < 10 ms target. Profiling rather
than guessing found `get_cached` alone was 6.09 ms of it: the cache stored a dict, so every hit
`json.loads`-ed 478 KB and DRF immediately re-encoded it — about 11 ms of round-tripping to turn
JSON into JSON.

Entries now store the exact bytes of `JSONRenderer().render(data)` and a hit returns them via
`HttpResponse` untouched. **3.44× faster (11.35 → 3.30 ms)** and byte-identity with the miss path
is by construction — the miss path renders with the same renderer instance before caching — rather
than by coincidence. `test_hit_is_byte_identical_to_what_the_miss_path_renders` pins it.

### Zero-staleness evidence

Not asserted from a passing test alone; the full chain was observed:

```
version before write : 15   (2nd read was a HIT: 4.33 ms)
target issue         : c26e007a…  hours=24.0
version after write  : 16   -> bump fired: True
re-read latency      : 100.61 ms -> was a MISS (recomputed): True
hours after write    : 27.5   expected 27.5
VERDICT              : ZERO STALENESS
```

The re-read latency is the load-bearing line: 100.61 ms proves the response was recomputed rather
than served from a stale entry that happened to hold the right number.

**One earlier probe reported `STALE!` and was wrong.** It selected an issue whose estimate was
`0.0`; raising it to `3.5` re-sorted the item out of the capped 200-task set (`_task_sort_key`
places unestimated first), so the lookup returned `None` — absence, not staleness. Recorded because
a red for the wrong reason is exactly as untrustworthy as a false green.

### The coverage test was proven, not assumed

`TestReceiverCoverage` was deliberately broken — the `State` receivers removed — and observed
failing with `No post_save version-bump receiver for: ['State']` before being restored. A gate
never seen failing is unproven (`rules/green-that-proves-nothing.md`).

### The evicted-version-key risk — found, then REPRODUCED, then closed

An earlier revision of this section recorded this as "unlikely rather than
theoretical" and left it unmitigated. **Phase 5's criterion 5 reproduced it.**

Filling staging's db1 to its 1 GB bound (2026-08-27) evicted **112,784 keys —
including every `wlc:ver:*`**, and also evicted core's single db0 key. The
"unlikely" reasoning had been that the version key is each workspace's hottest
key and LRU evicts coldest-first; that holds in steady state and does not hold
under a bulk sweep, where 300k newer keys make everything pre-existing look cold.

Two things followed.

**1. Absence now means "do not serve", never a default version.** A reader that
substituted a default would look for entries under it and serve anything that
survived the same sweep as though fresh. A miss is always safe; a wrong version
is not.

**2. The version became a random token instead of an `INCR` counter.** Absence
handling alone was not enough: a counter has to restart from _something_ after
eviction, and anything it restarts from can re-enter a range that surviving
entries were written under. Seeding the restart from the server clock narrows
that and does not close it — a burst of bumps outruns the clock, and
`test_recreated_version_cannot_re_reach_surviving_entries` failed on precisely
that, reseeding to `1800000000` while versions already used had reached
`1800000002`. A random token cannot collide with any token ever used, so the
class of problem disappears rather than becoming improbable.

That test was written to pin the fix and instead **failed against the fix**,
which is what caught the clock-seeding flaw before it shipped.

**Criterion 5 is recorded as FAILED, not adjusted.** Core's db0 key _was_
evicted under fork pressure, so D5's containment claim ("core keys should always
rank hot") is wrong under a bulk fill. The consequence is mild — db0 holds
TTL-bearing `cache_response` entries that rebuild on the next request, verified
by `/api/instances/` returning 200 and db0 repopulating immediately — but the
claim was wrong and is corrected rather than re-scoped.

### Superseded: the original note on this risk

`wlc:ver:{slug}` counters carry no expiry, like every other key (D6), and are therefore **eligible
for `allkeys-lru` eviction**. If a counter is evicted it reads as `0` again, and any surviving
`v0` entry for that workspace — written before its first bump and not yet evicted itself — would
be served as though fresh. That is a genuine silent-staleness path, the one this design otherwise
closes.

**Why it is unlikely rather than theoretical:** the counter is read on _every_ request for its
workspace, making it that workspace's hottest key, while payload entries are read far less often
and are ~320 KB each. LRU should evict payloads long before counters. Unlikely is not impossible,
though, and the failure is silent, so it is recorded rather than reasoned away.

**Not yet mitigated.** Options for Phase 5 or a follow-up, in rough order of preference: have
`get_cached_bytes` treat a _missing_ counter as "do not serve" rather than as version 0 (turning
the failure into a miss, which is the safe direction); or persist counters outside the LRU
keyspace. Do not reach for `volatile-lru` — it would make the no-TTL entries entirely unevictable,
which is the failure Phase 1 exists to remove.

**Operational note:** running the test suite against a shared Redis leaves one counter per
throwaway workspace behind, and they never expire. A verification run on 2026-08-27 left 725 such
keys (8.12 MB) in staging's db1; they were flushed after confirming db1 held no non-`wlc:` keys.
Phase 5's harness should use a dedicated db index or clean up after itself.

### Corrections to the plan made during implementation

1. **`views_ext` cannot use a closed allow-list.** The contract prescribed hashing an allow-list of
   response-affecting params. That is safe for `workload/`, whose `_parse_common` returns a fixed
   validated dict, but **wrong** for `views_ext/`, which feeds `request.query_params` through
   `issue_filters()` and a `ComplexFilterBackend` filterset — an open, independently-evolving
   surface. An allow-list there would silently serve one filter's results under another's key the
   moment core adds a filter. `views_ext` now hashes the full normalized query string;
   `keys.py` documents both modes and which is safe where.
2. **The write-path memo in phase-3 was wrong.** It called for avoiding a per-write slug lookup.
   Measured, that lookup is 0.367 ms against a 0.717 ms bare `Issue.save()`, and at ~58 writes/hour
   totals ~21 ms of database time per hour. A process-local memo would also go stale on a workspace
   rename in every worker except the one that handled it, since signals are in-process — bumping the
   old slug forever while reads under the new one were never invalidated. Reading fresh is simpler
   and is the only variant that cannot silently serve stale data.
3. **`plane/settings/redis.py:22` already pins core to `db=0` explicitly**, which confirms the D5
   split against the source rather than leaving it an assumption.

## Propagation (per CLAUDE.md standing rule)

No new endpoint, field, or request/response shape is introduced — this is caching and optimization
behind existing contracts — so `plane-mcp-server` / SDK bindings need **no** change. Phase 5 adds
the `CLAUDE.md` "Custom features" entry for `workload_cache/` and records the db1 convention in
`docs/FORK.md`. If Phase 4 alters any response field, that becomes a propagation obligation and
Phase 5 must open the sibling-repo issues; it is not expected to.
