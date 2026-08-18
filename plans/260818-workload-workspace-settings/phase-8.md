# Phase 8 — Workload timeline UI (replaces the matrix)

**Goal:** replace the aggregate table with per-member swimlanes of task bars, built on core's
existing Timeline (gantt) layout. Depends on Phase 4 (`useWorkSettings`) and Phase 7 (task rows).

Parent plan: [`plan.md`](plan.md).

## Target layout

```
┌─ sidebar ───────────────┬─ chart (day columns, today marked) ─────────────┐
│ ◯ Hiếu Ngô Văn  32h/40h │  8h    │  8h    │  8h    │  8h    │  0h        │  ← capacity heat row
│                    ⌄    │ ▬ Fix feedback 8h │ ▬ Chapter Reuse 8h │        │  ← task bars
│ Unscheduled  Overdue    │                                                 │
├─────────────────────────┼─────────────────────────────────────────────────┤
│ ◯ Lê Văn Hiếu   15h/40h │  0h    │  0h    │  5h    │ 10h    │  0h        │
└─────────────────────────┴─────────────────────────────────────────────────┘
```

Per member: avatar + name, a `used/capacity` badge, a collapse chevron, an "Unscheduled tasks"
and "Overdue tasks" affordance, one heat cell per day, and task bars that may span days.

## Ownership

- `apps/web/core/components/workload/timeline/**` (new)
- `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx`
- `packages/workload-ext/src/**` (store/service/types only — the view leaves the package)

## What is reused, and what is not (D12)

| Reused from `@/components/gantt-chart` | Why it fits |
|---|---|
| `ChartViewRoot` + `GanttChartMainContent` | Generic over `blockIds`, `blockToRender`, `sidebarToRender` (`chart/root.tsx:25-47`) |
| `weekView` / `monthView` / `quarterView` + `currentViewDataWithView` | Supplies the day-column axis; `populateDaysForWeek` already emits per-day blocks |
| `showToday` | The today marker in the mock |
| `useTimeLineChartStore`, `getNumberOfDaysBetweenTwoDates`, `SIDEBAR_WIDTH` | Block positioning maths and sidebar alignment |

**Not provided — this is the real work:**

- **Swimlane grouping.** The gantt renders a flat `blockIds` list; there is no group seam
  (`sidebar/root.tsx`, and the issue layout passes a flat array at
  `issues/issue-layouts/gantt/base-gantt-root.tsx:197`). Compose grouping *around* the exported
  primitives — one chart instance, the workload view owning the per-assignee sections — before
  considering an edit to `ChartViewRoot`. An edit there is a fenced core exception and a rebase
  conflict point; decide it in this phase with the composition attempt as evidence, not upfront.
- **The capacity heat row.** Per-day aggregate hours coloured against the workspace capacity:
  under → success, at → warning, over → danger. Values come from `row.buckets` and
  `row.capacity_buckets`, both of which the API already returns.
- **The `used/capacity` badge** — `row.total` over the summed `capacity_buckets` for the visible
  range, not the raw weekly max, or the badge lies on any range that isn't exactly one week.

**Out of scope (D14):** drag-to-reschedule. Pass `enableBlockMove`, `enableBlockLeftResize`,
`enableBlockRightResize`, `enableReorder`, `enableDependency`, `enableAddBlock` as `false`.

## Placement (D13)

`packages/workload-ext` **cannot** import `@/components/gantt-chart` — that alias is
app-internal. The timeline therefore lives under `apps/web/core/components/workload/timeline/`
as NEW files (additive, like the existing `estimated-hours-column.tsx` precedent), and the
package is reduced to store, service, types, and `dateRange.ts`.

This is a move, not a rewrite of behaviour: `store.ts` / `service.ts` / `types.ts` stay where
they are and keep their tests.

## Matrix removal

`WorkloadMatrix.tsx` is deleted (the `<Table>` render at lines 196-270 and the `CapacityBadge`
already removed in Phase 4). `WorkloadToolbar` is kept — granularity, filters, and the
over-capacity toggle all still apply — with the settings readout from Phase 4.

The over-capacity filter now hides whole swimlanes rather than table rows.

## Tasks

1. Move the view layer out of `packages/workload-ext`; keep store/service/types.
2. Timeline shell: chart instance, day axis, today marker, zoom wired to granularity.
3. Sidebar row: avatar, name, `used/capacity` badge, collapse chevron.
4. Capacity heat row per swimlane.
5. Task bars from Phase 7's `tasks`, positioned via the gantt helpers; label = name + hours.
6. Unscheduled + overdue affordances per member, and the `tasks_truncated` flag surfaced.
7. Delete `WorkloadMatrix.tsx`; rewire the route page.
8. i18n for the new strings.

## Success criteria

- `pnpm check` clean.
- A task spanning Mon–Wed renders as **one** bar three columns wide, not three bars.
- Collapsing a member hides its bars and heat row but keeps the axis aligned across members.
- A member over capacity on one day shows that day in the danger colour and still totals
  correctly in the badge.
- `tasks_truncated: true` renders a visible "showing first N" affordance — never a silently
  short list.
- `grep -rn "WorkloadMatrix" apps packages | grep -v node_modules` returns zero hits.
