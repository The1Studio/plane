# Phase 7 — Backend: per-task payload + overdue flag

**Goal:** emit the per-issue rows the timeline needs. Depends on Phase 3 (the service already
reads workspace settings and workday-aware aggregation by then).

Parent plan: [`plan.md`](plan.md). Contract: [`phase-0.md`](phase-0.md).

## Why this phase exists

The workload endpoint today returns **aggregated buckets only** — `service.py:325-362` builds
`{period: hours}` per assignee and discards which issues produced them. The timeline renders a
bar per task, so the per-issue detail that `spread_estimate()` already computes mid-loop has to
survive into the response instead of being summed away.

## Ownership

- `apps/api/plane/workload/service.py`
- `apps/api/plane/workload/tests/test_task_rows.py` (new)

## Response shape (extends the Phase 0 contract)

Each assignee row gains a `tasks` array:

```jsonc
{
  "assignee_id": "…", "assignee_name": "…",
  "buckets": { "2026-08-10": 8.0 },        // unchanged
  "tasks": [
    {
      "id": "…",                  // issue uuid
      "identifier": "PLANE-12",   // human-readable, for the bar label
      "name": "Fix feedback release 1",
      "hours": 8.0,               // the issue's full estimate, not the windowed slice
      "start_date": "2026-08-10", // may be null
      "target_date": "2026-08-10",// may be null -> unscheduled
      "state_group": "started",
      "overdue": false
    }
  ],
  "tasks_truncated": false
}
```

`hours` is the issue's **whole** estimate so the bar label matches the work item, while
`buckets` stays the windowed, workday-spread distribution. These two deliberately do not
reconcile for an issue whose span is clipped by the window — document it in the serializer
docstring, because a reader will otherwise treat the mismatch as a bug.

## Overdue

`overdue = target_date < today AND state_group NOT IN ("completed", "cancelled")`.

`today` is resolved in the **workspace's** timezone, not the server's — a task is not overdue
because UTC rolled over. Plane's `Project.timezone` exists; the workspace-level equivalent must
be confirmed in this phase, and if there is none, fall back to the project timezone and say so
in the docstring rather than silently using UTC.

## Truncation cap

A workspace with thousands of estimated issues would return an unbounded array. Cap tasks per
assignee (`WORKLOAD_MAX_TASKS_PER_ASSIGNEE`, start at 200), ordered by `start_date` then
`target_date`, and set `tasks_truncated: true` on any row that was cut. **A truncated row must
be visibly flagged in the UI** — a silently short list reads as "this person has no more work".

## Tasks

1. Thread per-issue detail through the aggregation loop instead of discarding it.
2. Add the `tasks` array + `tasks_truncated` to the row serializer.
3. Overdue derivation + timezone resolution.
4. Cap + ordering.
5. Tests: task appears on the right assignee; unscheduled task has null `target_date`;
   overdue flag flips on a past target with an open state and stays false for a completed one;
   truncation sets the flag; a task spanning 3 days appears once in `tasks` while contributing
   to 3 `buckets` entries.

## Success criteria

- `python manage.py check` clean; workload suite green.
- A workspace with one 3-day task returns exactly one `tasks` entry and three non-zero buckets.
- No N+1: the issue rows come from the query the aggregation already runs — verify with
  `assertNumQueries`, not by inspection.
