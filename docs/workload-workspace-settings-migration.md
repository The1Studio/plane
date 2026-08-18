# Workload workspace settings — operator migration note

**Read this before deploying `plans/260818-workload-workspace-settings/`.** It replaces
per-member workload capacity with one workspace-wide setting, changes how hours are spread
across days, and replaces the Workload page's table with a timeline. Nothing here requires
manual data entry to complete the migration — it is fully automatic — but four things about
existing data and existing UI change in ways worth knowing before someone asks "why did my
numbers move?"

## 1. Day and week totals will change, even though no estimate was edited

Estimated hours used to spread evenly across every **calendar** day of an issue's date span.
They now spread only across the **configured workdays** (Monday–Friday by default). An issue
with the same start/target dates and the same estimate as yesterday can now show different
numbers on individual days and weeks, because the hours that used to land on a Saturday or
Sunday now land on the surrounding workdays instead.

**What does NOT change:** the issue's total estimated hours, and any **monthly** total (a month
contains the same total hours either way; only their day/week placement shifts).

## 2. Per-member capacity is gone — replaced by one workspace-wide maximum

There is no longer a per-person weekly-capacity setting. A single **workspace-wide** maximum
weekly hours value (default **40h**, adjustable by any workspace admin at
`/:workspaceSlug/settings/workload`) now applies to every member equally.

**Existing per-member capacity values are not carried forward and are not recoverable.** The
migration does **not** average, maximize, or otherwise derive the new workspace default from
old per-member values — every workspace is seeded with the same fixed default (40h /
Monday–Friday / week starts Monday), which an admin can change once after the deploy if 40h is
wrong for that workspace. The old per-member table is dropped by the migration; reversing the
migration recreates an empty table, not the old rows. If you need a record of what the old
per-member values were, capture it **before** this deploys:

```sql
SELECT * FROM workload_capacities;
```

## 3. Week-bucket keys in the Workload API changed format

`GET /api/v1/workspaces/<slug>/workload/?granularity=week&...` used to key each week's bucket
with an ISO week number (`"2026-W34"`). It now keys each week bucket with the **date of that
week's first day** (`"2026-08-17"`), because a workspace-configurable week start has no ISO
week number to fall back to. Any external client parsing the old `YYYY-Www` shape will break —
see the sibling-repo propagation issues below for the SDK/MCP/docs updates this requires.

## 4. The per-user "start of week" preference is gone — a workspace admin now owns it

Profile → Preferences no longer has a "start of week" control, and the matching Power-K command
was removed. Week start (which day calendars, date pickers, and the workload timeline treat as
the first day of the week) is now set once, workspace-wide, by an admin at
`/:workspaceSlug/settings/workload` — the same page as the hours/workdays setting above. Any
individual member who had customized their own start-of-week preference will see the workspace
value instead after this deploys.

## 5. The Workload page is now a per-member timeline, not a table

`/:workspaceSlug/workload` no longer renders the aggregate hours-per-week matrix. It renders a
per-member timeline (one swimlane per assignee, task bars positioned by start/target date,
color-coded by over/under the workspace capacity), built on the same Timeline (gantt) component
used elsewhere in the product. Drag-to-reschedule from this view is intentionally not supported
yet (out of scope, `plan.md` D14) — bars are read-only.

## New API surface

`GET|PUT /api/v1/workspaces/<slug>/work-settings/` — the workspace's max weekly hours, workdays,
and week-start day. Admin-write, member-read.
