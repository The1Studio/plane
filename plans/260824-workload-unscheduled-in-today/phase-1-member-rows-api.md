# Phase 1 — a swimlane for every member, loaded or not

**Owns:** `apps/api/plane/workload/service.py`,
`apps/api/plane/workload/tests/test_member_rows.py` *(new)*
**Estimate:** 3h
**Depends on:** nothing. **Not blocked by PLANE-120** — see plan.md § Status.

## Goal

A member who carries no estimated work disappears from the workload timeline entirely. Give them a
row, so the board answers "who is free" as well as "who is overloaded".

## Why the row is missing today

`compute_workload` derives its row set from the estimates it just summed:

```python
# service.py:534
owner_ids = set(buckets.keys()) | set(unscheduled.keys()) | set(month_buckets.keys())
```

Every one of those three maps is keyed by an owner that appeared on an issue carrying a
`WorkloadEstimate` with `hours > 0` (`_base_queryset`). So a member vanishes in **two** different
situations that look identical from the outside:

1. They have no assigned work item at all.
2. They have assigned work items, but nobody estimated any of them.

Both are the same absence to a reader, and D14 treats them the same way — driving rows off the
member list rather than off the estimates makes the distinction disappear on its own, with no
second query and no special case.

## The membership predicate — reuse, do not invent

`_resolve_owners` (`service.py:222`) already decides who is allowed to *be* an assignee here:
non-bot, not soft-deleted, and an **active `ProjectMember` of the issue's own project**. D11 reuses
exactly that. The symmetry is the point: a member gets a lane if and only if they could have been
assigned work that this request can see. Anyone else would get a lane nobody could ever fill.

Add a helper next to `_resolve_owners` so the two sit together and are read together:

```python
def _scope_member_ids(project_ids):
    """(assignee_id, display_name) for every member who COULD carry work in scope.

    Mirrors `_resolve_owners`' predicate exactly — active ProjectMember,
    non-bot, not soft-deleted — because the two answer halves of one question:
    that function says who owns the work that exists, this one says who could
    have owned work at all. If they ever disagree, a member can hold a bar the
    board refuses to give a lane to, or hold a lane no assignment can reach.

    Deliberately NOT WorkspaceMember: a member of the workspace with no project
    in scope cannot be assigned anything this request returns, so a row for them
    is a permanently empty lane, not information.
    """
```

One query over `ProjectMember` filtered to `project_ids` (the resolved scope, **not** the requested
ids — `resolve_project_scope` is the access boundary and must stay the only thing that decides what
is readable), `is_active=True`, `member__is_bot=False`, `member__deleted_at__isnull=True`,
`deleted_at__isnull=True`. Return distinct `(member_id, member__display_name)` — a member of three
in-scope projects must yield one row, not three.

## Wiring it in

```python
member_rows = _scope_member_ids(scope.project_ids)   # or however scope exposes them
owner_ids = set(buckets) | set(unscheduled) | set(month_buckets) | {mid for mid, _ in member_rows}
```

Two details that are easy to get wrong:

- **Feed `names` too.** `assignee_name` is read as `names.get(owner_id, "Unassigned")`
  (`service.py:582`). A member id that reaches `owner_ids` without a `names` entry renders as a
  **second row literally called "Unassigned"**, which is worse than the row being missing. Populate
  `names` from the same query, without overwriting a name an issue already supplied.
- **Honour the assignee filter (D15).** `assignee_filter` is applied per-issue-owner at
  `service.py:427` and never touches `owner_ids`, so an unfiltered union would keep every member's
  empty lane on screen while the loaded lanes narrowed to one person. Intersect the member ids with
  `assignee_filter` when it is set. Filtering to one member must show one lane.

Everything downstream then works unchanged: the per-owner loop reads `buckets.get(owner_id, {})`
and `tasks_by_owner.get(owner_id, [])`, both of which already default to empty. An empty row comes
out with `buckets: {}`, `total: 0.0`, `tasks: []`, `tasks_truncated: false`, `over` all-false, and a
**full `capacity_buckets`** — which is the entire value of the row: it says how much capacity is
going unused, in the same units as everyone else's.

Sorting is untouched (D13). The existing rule — `Unassigned` pinned first, then ascending by
`assignee_name` case-insensitively — already places an empty member exactly where a reader scanning
for their name expects.

## What this does NOT change

- **No new model, no migration, no touch-point entry.** `workload/` is an installed fork app
  already; this is one function and one union inside it.
- **`get_workload_rollups` is a separate path** (`rollup.py`, its own CTE) and does not read
  `owner_ids`. Leave it alone.
- **`ROW_GUARD`** guards estimate rows, not member rows. A member list is bounded by headcount and
  needs no new guard.
- **`meta`** counts issues, not rows. Nothing in it moves.

## Response-shape change — this is the propagating part

D12 makes this **unconditional**: no `include_empty_members` parameter, no opt-in. Every existing
`get_workload` consumer therefore starts receiving rows it has never seen — rows whose `total` is
`0` and whose `tasks` is empty.

Any consumer that treats `len(rows)` as "is there work here" is now wrong. One already does, in
this repo, and phase 2 fixes it. Phase 6 carries the same warning to `plane-mcp-server`'s
`get_workload` docstring, because an MCP caller reading row count as a work signal will make the
identical mistake with no way to see it coming.

## Tests

`apps/api/plane/workload/tests/test_member_rows.py`, following the DB-test style already in
`test_workload_db.py`:

| Case | Assertion |
| --- | --- |
| Active member, zero assigned issues | A row exists, `total == 0`, `tasks == []` |
| Active member, issues assigned but none estimated | A row exists — the second invisibility case, D14 |
| Member with work | Row unchanged from today: same buckets, same total |
| The empty row's `assignee_name` | Their display name — **never** `"Unassigned"` |
| `capacity_buckets` on an empty row | Fully populated, equal to a loaded member's for the same window |
| Bot member | **No** row |
| Inactive `ProjectMember` | **No** row |
| Member of an out-of-scope project only | **No** row |
| Member of three in-scope projects | Exactly **one** row |
| `assignee_ids=[X]` set | Only X's row, whether X is loaded or not (D15) |
| `Unassigned` bucket | Still pinned first, still exactly one |
| Row ordering | Alphabetical, empty and loaded interleaved (D13) |

The bot and inactive cases are not padding: they are the two ways the predicate silently widens if
someone later reaches for `WorkspaceMember` or drops a filter, and neither would be visible in a
response anyone eyeballs.

## Done when

`pytest apps/api/plane/workload/tests/ -q` is green, and a `GET` against a workspace with a
deliberately unassigned member returns their row with `total: 0` and a populated `capacity_buckets`.
