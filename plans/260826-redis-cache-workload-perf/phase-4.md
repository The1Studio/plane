# Phase 4 — Miss-path optimization

**Goal:** make the cache-miss path meaningfully faster, so a low hit rate is acceptable rather than
a failure — and so the 1147 ms cold spike comes down.

**Depends on:** nothing. Runs in parallel with Phases 1 and 2. Does **not** depend on the cache
existing; this phase must stand on its own with caching disabled.

**Owns:** `apps/api/plane/workload/service.py`, `apps/api/plane/workload/aggregation.py`.

---

## The measured budget, and a correction to carry

`compute_workload` at `granularity=week`, 90-day span, workspace `cocos`:

- **13 queries, 38.0 ms of SQL**
- **~99 ms wall**
- Therefore **~61 ms (62%) is Python aggregation plus DRF serialization of a 478 KB payload.**

**Query tuning alone cannot reach a 50 ms miss path.** Even eliminating _all_ SQL leaves ~61 ms.
The target is **< 75 ms** and it requires attacking both halves. Do not revise this target to
whatever a run happens to report.

## SQL half — ~38 ms available, realistically ~12 ms recoverable

| #    | ms    | Table                | Opportunity                                                                                                                                                                               |
| ---- | ----- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 12   | 15.00 | `issue_assignees`    | Largest single query. Check the index on `(issue_id, assignee_id)` and whether the `users` join for `display_name` can be deferred or served from the roster already fetched in query 13. |
| 10   | 6.00  | `issues`             | Main fetch. Already narrow; likely near floor.                                                                                                                                            |
| 9    | 5.00  | `workload_estimates` | Main fetch. Likely near floor.                                                                                                                                                            |
| 8    | 5.00  | `issues`             | `COUNT(*)` cap check                                                                                                                                                                      |
| 7    | 4.00  | `workload_estimates` | `COUNT(*)` cap check                                                                                                                                                                      |
| 11   | 1.00  | `workload_estimates` | `COUNT(*)` cap check                                                                                                                                                                      |
| 1, 5 | ~0    | `workspace_members`  | **#5 duplicates #1 verbatim** — resolve once per request                                                                                                                                  |
| 2, 6 | ~1    | `project_members`    | Near-duplicate `project_id` scans                                                                                                                                                         |

Two concrete targets:

1. **The three `COUNT(*)` cap checks (10 ms combined).** These enforce `WorkloadTooLarge` /
   truncation caps. A `COUNT` that exists only to compare against a cap can often be replaced by
   fetching `cap + 1` rows and checking the length — one query instead of two. Confirm the caps'
   semantics in `service.py` before changing; `_SPAN_CAPS` and the 200-task cap interact with
   `_task_sort_key` ordering (CLAUDE.md), and truncation order is observable behaviour.
2. **Duplicate permission scans (#1/#5, #2/#6).** Resolve project scope once and thread it through
   rather than re-deriving. `resolve_project_scope` is already called once at `service.py:512`;
   find the second caller.

## Python/serialization half — ~61 ms, the larger target

Not yet attributed between aggregation and DRF. **Profile before optimizing** — the split is
unmeasured, and guessing here is how the wrong half gets optimized:

```bash
ssh server 'docker exec plane-staging-app-api-1 sh -c "cd /code && python -c \"
import cProfile, pstats
...compute_workload(...)
\""'
```

Likely candidates, to be confirmed by the profile rather than assumed:

- 478 KB of JSON for ~1,274 tasks across 31 rows. Per-task dict construction in
  `aggregation.py` is the obvious hot loop.
- DRF's `Response` rendering of a large nested structure. If the payload is already plain dicts,
  a direct `JsonResponse` with a fast serializer may skip a full render pass.
- `month_buckets` is emitted at every granularity (CLAUDE.md) — confirm it is computed once, not
  per row.

## Golden-fixture gate — do this first

Optimization must not change output. **Before touching either half**, capture the current response
for a matrix of inputs and pin it:

- granularities `day` / `week` / `month`
- spans 30 / 90 / 365 days
- with and without `project_ids`, `assignee_ids`, `state_groups`
- a guest-restricted user and a full member
- a workspace with unestimated and unscheduled items present (both have specific documented
  packing behaviour)

Store as fixtures; assert byte-equality of the serialized response after every change. Any diff is
a failure, not a judgement call.

This is an **input-integrity guard**, not a pinned baseline — it pins known-_good_ current output
so the optimization below cannot pass vacuously. It fires on a behaviour change, never on a fix,
so it needs no companion assertion (`rules/pinned-baseline-test-companion.md`).

## Steps

1. Build the golden fixtures and confirm they pass against unmodified code.
2. Profile the Python half; record the aggregation/serialization split as a measured number.
3. SQL: dedupe the permission scans, then fold the `COUNT(*)` checks.
4. Python: optimize whatever the profile actually named.
5. Re-measure end-to-end with caching **disabled**, so the number is the miss path.

## Success criteria

- Golden fixtures byte-identical across all matrix combinations.
- Miss-path median **< 75 ms** (from 98.8 ms), measured with caching off.
- Query count **< 13**, SQL **< 30 ms**.
- Max/cold spike **< 300 ms** (from 1147 ms).
- The aggregation-vs-serialization split is **reported as a measured number**, not estimated.

## Out of scope

Any change to the response shape. If an optimization would alter a field, stop — that becomes a
propagation obligation across `plane-mcp-server` and the SDKs (CLAUDE.md standing rule) and needs a
decision, not a quiet edit.
