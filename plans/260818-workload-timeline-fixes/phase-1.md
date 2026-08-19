# Phase 1 — API: window-complete periods, weekly buckets, `project_id`

**Goal:** make the capacity numbers mean what the UI claims, and hand the frontend the two fields
Phases 3 and 4 need. Parent: [`plan.md`](plan.md).

## Ownership

- `apps/api/plane/workload/aggregation.py`
- `apps/api/plane/workload/service.py`
- `apps/api/plane/workload/tests/**`
- `packages/workload-ext/src/types.ts` (type mirror only — no view code)

No migration: nothing is stored, all three additions are computed per request.

## 1.1 — `periods` spans the requested window (D2)

Today (`service.py:438-441`):

```python
period_set = set()
for pm in buckets.values():
    period_set.update(pm.keys())      # populated buckets ONLY
periods = sorted(period_set)
```

Replace with the union of _every_ period the window covers and the populated ones:

```python
periods = sorted(set(enumerate_periods(date_from, date_to, granularity, week_start_day)) | period_set)
```

`enumerate_periods(win_from, win_to, granularity, week_start_day)` is a new **pure** helper in
`aggregation.py`, next to `period_key` (which it must call — do not re-derive the key format):

- `day` — every date from `win_from` to `win_to`.
- `week` — `period_key(win_from, …)` then `+7d` until past `win_to`.
- `month` — `YYYY-MM` from `win_from`'s month through `win_to`'s month.

The union (not a replacement) matters: `spread_estimate` clips to the window but `period_key` is
computed on the un-clipped day, so a week bucket can legitimately key to a date one or two days
_before_ `date_from`. Dropping those would silently lose hours from the heat row.

**Consequences, both intended:** `capacity_buckets` (`:450`) and `total_capacity` (`:454`) now
cover the whole window, so `total_over` (`:467`) becomes a true window comparison; and `over`
(`:463-466`) gains a `False` entry for every empty period, which is what lets Phase 3 render a `0h`
cell there.

**Cost check:** `periods` is bounded by the existing `_SPAN_CAPS` (`views.py:35`) — at worst 92
day-periods, 53 week-periods, or 24 month-periods. `capacity_buckets` is built once per request and
shared by reference across rows (already true today), so this is O(periods), not O(rows × periods).

## 1.2 — `weekly_buckets` + `weekly_capacity` (D1)

The badge must read `NNh/40h` for one week at _any_ granularity, so it cannot be derived from
`buckets`. Add a second, always-weekly aggregation computed in the same loop over `est_rows`:

```python
wb, _, _ = spread_estimate(
    hours, start, target, date_from, date_to, "week", workdays, week_start_day
)
for k, c in wb.items():
    weekly[owner_id][k] += c
```

Emit on each row:

- `weekly_buckets: {week_key: hours}` — sparse, same key format `period_key(..., "week", …)` produces
  (the week's first date, per plan D10 of the parent plan — **not** an ISO week number).
- `weekly_capacity: float` — `max_weekly_hours`, the same value for every row (D1 of the parent
  plan made capacity workspace-wide). Emitted per row anyway so the frontend never has to reach
  into `meta` for it.

Skip the second call when `granularity == "week"` — reuse `b` directly.

**Why not a `focus_week` query param:** the server would then own a notion of "the week the user is
looking at", which it cannot know (the gantt axis scrolls freely and never round-trips). Returning
the whole map keeps focus a client concern and costs ≤53 floats per row.

## 1.3 — `project_id` on each task

`compute_workload` already joins the project for `issue__project__identifier` (`:349`). Add
`"issue__project_id"` to the same `values_list` and put `project_id` on the task dict beside
`identifier`. One extra column on an existing query — no N+1, no second fetch.

## 1.4 — Type mirror

Add to `packages/workload-ext/src/types.ts`: `TWorkloadTask.project_id: string`,
`TWorkloadRow.weekly_buckets: Record<string, number>`, `TWorkloadRow.weekly_capacity: number`.
Document on `weekly_buckets` that it is granularity-independent and that its key is a date, not an
ISO week.

## Tests

- `tests/test_aggregation_pure.py` — `enumerate_periods` for all three granularities, including a
  window whose first day is mid-week (the union case above) and a single-day window.
- `tests/test_workload_db.py` — a window with a zero-hour week returns that week in `periods` with a
  `capacity_buckets` entry and `over: False`.
- New `tests/test_weekly_buckets.py` — a task spanning a weekend lands in one week bucket;
  `weekly_buckets` is identical for the same data at `granularity=day`, `week`, and `month`.
- `tests/test_task_rows.py` — `project_id` present and matches the issue's project.

## Success criteria

- `pytest apps/api/plane/workload/tests` green.
- `python manage.py makemigrations --check --dry-run` clean (proves no model change crept in).
- A request over Aug 18 – Nov 10 at `granularity=week` returns 13 `periods`, not 3.
