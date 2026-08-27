# Phase 3 — Endpoint wiring and version-bump coverage

**Goal:** serve both fork endpoints from cache with **zero staleness**. This is the highest-risk
phase: a missed bump does not fail loudly, it silently serves stale data that looks fresh.

**Depends on:** Phase 2 (consumes its three public functions).

**Owns:** `apps/api/plane/workload/views.py`, `apps/api/plane/views_ext/views.py`, and
`apps/api/plane/workload_cache/signals.py` (Phase 2 creates the file; this phase fills its model
coverage).

**Contract:** [`references/cache-contract.md`](references/cache-contract.md). Call only
`get_cached_bytes` / `render_json` / `set_cached` / `bump_workspace` and return
`CachedJSONResponse`. Do **not** construct a key, touch the client, or read the version counter
directly.

**Status: implemented 2026-08-27** (commit `ff8edbdf3b`). Where the guidance below was disproved by
measurement, the correction is marked inline rather than the original being quietly deleted.

---

## Read-side wiring

`WorkspaceWorkloadEndpoint` and `ProjectWorkloadEndpoint` (`plane/workload/views.py:293,301`), and
`GroupedWorkspaceViewIssuesEndpoint` (`plane/views_ext/views.py:183`).

Cache **after** permission resolution, never before — the key includes `user_id` precisely because
results are permission-scoped, and a guest in a restricted project must not be served another
user's row set. `compute_workload` resolves scope internally via `resolve_project_scope`
(`service.py:512`), so the cached value is already user-specific; the key must reflect that and the
permission check must still run on every request, hit or miss.

Cache only `200` responses. A cached `400` or `404` would outlive the condition that caused it.

`GroupedWorkspaceUserProfileIssuesEndpoint` (`views_ext/views.py:367`) is **in scope** for the same
treatment; it was not benchmarked, so measure it in Phase 5 before claiming a result for it.

### The `search` param

`views_ext` accepts an ephemeral `search` param (CLAUDE.md). It changes the response, so it belongs
in `params_hash` — but a high-cardinality free-text param fragments the keyspace badly. **Do not
cache requests carrying a non-empty `search`.** Empty or absent `search` returns everything and is
the common, cacheable case.

## Write-side coverage — the crux

A bump must fire for **every** write that can move a bar, including writes in core code this fork
does not own. Per-endpoint calls in `plane/workload/views.py` would cover only fork-owned writes
and miss core's issue editing entirely — which is the majority of the measured 22.31 issue
writes/hour. **Signals, not endpoint calls**, is the reason this is a `post_save`/`post_delete`
design.

Derived from the 13 queries `compute_workload` actually runs (`plan.md` § query breakdown) — each
model below is read by the endpoint, so a change to it can change the response:

| Model              | Why it affects output                                                               | Slug resolution         |
| ------------------ | ----------------------------------------------------------------------------------- | ----------------------- |
| `WorkloadEstimate` | hours per issue (queries 7, 9, 11)                                                  | `instance.workspace_id` |
| `Issue`            | `start_date`, `target_date`, `name`, state (queries 8, 10)                          | `instance.workspace_id` |
| `IssueAssignee`    | which swimlane a bar sits in (query 12)                                             | `instance.workspace_id` |
| `WorkloadSettings` | `max_daily_hours`, workdays, week start (query 3)                                   | `instance.workspace_id` |
| `ProjectMember`    | which rows exist at all — every active member gets a row (queries 2, 6, 13)         | `instance.workspace_id` |
| `State`            | `state_name` / `state_color` on every bar                                           | `instance.workspace_id` |
| `Workspace`        | `timezone`, which sets the workspace-local "today" and the `overdue` flag (query 4) | `instance.slug`         |

`Project` is deliberately **absent**: a project rename does not appear in the response
(`tasks[].project_id` is a UUID). If Phase 4 or a later change surfaces a project name, this table
gains a row — note that dependency rather than leaving it implicit.

**Slug resolution — this guidance was WRONG and is corrected.** The original text called for a memo
to avoid a per-write slug lookup. Two things were found on implementing it:

1. **Every one of these models carries `workspace_id` directly** — the four `ProjectBaseModel`
   subclasses inherit it, and both workload models declare it explicitly. So the "three
   dereferences" the original feared never existed; the `instance.issue.workspace.slug` column in
   the table above was wrong for `WorkloadEstimate` and `IssueAssignee` alike.
2. **The remaining `workspace_id` -> slug lookup costs 0.367 ms**, against a 0.717 ms bare
   `Issue.save()`, at a measured ~58 writes/hour across all workspaces — about **21 ms of database
   time per hour** in total. Building machinery to save that is the premature optimization the
   guidance itself warns against elsewhere.

A memo is also _incorrect_, not merely unnecessary: signals are in-process, so a workspace rename
handled by one worker leaves every other worker's memo stale, bumping the old slug forever while
reads under the new one are never invalidated. Reading fresh is simpler and is the only variant
that cannot silently serve stale data.

## Steps

1. Fill `signals.py` with receivers for the seven models above.
2. Wire `get_cached` / `set_cached` into the three read endpoints, after permission resolution,
   `200`-only, skipping non-empty `search`.
3. Add the slug-resolution helper and confirm by query count that a write adds **zero** queries.
4. Verify bump coverage empirically — the test below is the phase's real deliverable.

## Tests

- **Zero-staleness, per model.** For each of the seven: read the endpoint (populating cache), write
  the model, re-read, assert the response reflects the write. This is the test that would catch a
  missing receiver, and it must be parameterized over the model list so adding a model without a
  receiver fails.
- **Bump does not scan.** Assert `bump_workspace` issues `INCR` and no `KEYS`/`SCAN` — patch the
  client and inspect calls. Guards against someone "fixing" invalidation by sweeping keys.
- **User isolation.** Two users with different project scopes get different cached payloads.
- **`search` bypass.** A request with non-empty `search` never writes a cache entry.
- **Write path adds no queries.** `assertNumQueries` around an issue save, before and after.

## Success criteria

- Every zero-staleness test passes for all seven models.
- An issue save costs the same query count as before this phase.
- Warm-cache `GET …/workload/` median **< 10 ms**, and the run reports cache hit rate alongside so
  a fast miss cannot be mistaken for a hit.
- `python manage.py makemigrations --check --dry-run` clean.

## Known gap, recorded not fixed

Core's `invalidate_cache(multiple=True)` still issues a blocking `KEYS` on db0
(`plane/utils/cache.py:66`). D5 contains it — fork keys live on db1, so core's sweeps never see
them — but the core hazard itself remains. Fixing it is a core-file edit, outside D1's scope. Do
not silently "fix" it here; that is how a core edit enters the fork without a decision.
