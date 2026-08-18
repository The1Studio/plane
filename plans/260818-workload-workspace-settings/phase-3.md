# Phase 3 — Service wiring + `WorkloadCapacity` removal

**Goal:** feed the workspace settings into the workload query, and delete the per-member capacity
grain. Depends on Phases 1 and 2.

Parent plan: [`plan.md`](plan.md).

## Ownership

- `apps/api/plane/workload/service.py`
- `apps/api/plane/workload/models.py` (removal only — the additive part landed in Phase 1)
- `apps/api/plane/workload/views.py` / `api_views.py` / `urls.py` / `api_urls.py` (capacity route removal)
- `apps/api/plane/workload/migrations/` (data migration + delete migration)
- `apps/api/plane/workload/tests/` (non-pure)

## Service changes

`service.py:325-362` currently resolves per-owner capacity via `_resolve_capacities(owner_ids, slug)`
and produces `capacity_buckets` / `over` / `total_over` per row.

New shape:

1. Read the workspace's `WorkloadSettings` **once per request** (defaults if no row) — not per row.
2. `_resolve_capacities` is **deleted**. Every row uses the same `max_weekly_hours`.
3. `capacity_buckets` is now identical for every row, so compute it **once** and reference it:
   ```python
   capacity_buckets = {p: capacity_for_period(max_weekly_hours, p, granularity, workdays)
                       for p in periods}
   ```
   Keep emitting it per row in the response so the frontend contract does not change shape — but
   consider hoisting it to a top-level response key if the payload size matters (measure first; do
   not hoist speculatively).
4. `over` / `total_over` logic is unchanged apart from reading the shared buckets.
5. The `weekly_capacity is not None` branch disappears — there is always an effective capacity now.
   **Consequence:** every row now carries `over`/`total_over` flags, where previously only members
   with an explicit capacity row did. This is intended (D1) and is the user-visible upside.
6. Every `period_key` / `spread_estimate` / `capacity_for_period` call site passes `workdays` and
   `week_start_day` from the settings.

There is **no period-enumeration code in `views.py`** — an earlier draft of this file claimed there
was. `periods` appears zero times in `views.py` and `api_views.py`; the list is built entirely
inside `service.py` from the bucket keys `spread_estimate` returns. Once `workdays` and
`week_start_day` are threaded through that call, the new `YYYY-MM-DD` week format falls out
automatically and no separate generator needs updating.

## Capacity removal

Order matters; three migrations in sequence:

1. **Data migration** — create a `WorkloadSettings` row with the **default** `max_weekly_hours`
   (40) for every workspace that has `workload_capacities` rows but no settings row yet (D8).
   Existing per-member values are **not** read: the live data is a single placeholder `0`, and a
   `max()`-derived seed would render every member over-capacity on day one. Workspaces already
   carrying a settings row from a Phase 1 PUT are **not** overwritten. Write a `reverse_code` that
   recreates an empty table; document in the migration docstring that per-member values are **not**
   restorable. Do not use `RunPython.noop` for reverse.

   Before merging, capture `SELECT * FROM workload_capacities;` into the PR body — the only
   surviving record of the discarded values.

2. **`DeleteModel("WorkloadCapacity")`.**
3. Remove `WorkloadCapacitySerializer`, `capacity_list` / `capacity_put` / `capacity_delete`
   (`views.py:179-235`), the `WorkloadCapacityEndpoint` / `WorkloadCapacityAPIEndpoint` classes,
   and both URL entries (`urls.py:45-48`, `api_urls.py:46-49`).

Run a pre-delete reference check before step 3:

```bash
grep -rn "WorkloadCapacity\|workload-capacity\|capacity_list\|capacity_put\|capacity_delete" \
  apps packages --include="*.py" --include="*.ts" --include="*.tsx" | grep -v node_modules
```

Every hit must be resolved — including the frontend ones, which Phase 4 owns. If Phase 4 has not
landed, leave the frontend hits and note them; do **not** edit Phase 4's files from here.

## Tests

- Workload endpoint returns identical numbers to Phase 2's pure expectations for a seeded workspace.
- A member with no prior capacity row now receives `over` flags (the D1 behaviour change).
- `GET /api/workspaces/<slug>/workload-capacity/` → 404 (route gone).
- Data-migration test: workspace with rows `[0, 20, 35]` seeds `max_weekly_hours == 40` (the
  default, not a value derived from the rows).
- Data-migration test: workspace with an existing settings row is not overwritten.

## Success criteria

- `makemigrations --check --dry-run` clean.
- The pre-delete grep returns zero backend hits.
- Full workload suite green.
