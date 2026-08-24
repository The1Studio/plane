# Phase 5 — dragging an unscheduled bar onto a date

**Owns:** `apps/web/core/components/workload/timeline/useTaskBarDrag.ts`,
`apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`,
`packages/workload-ext/src/i18n.ts`
**Estimate:** 3h
**Depends on:** phase 4. PLANE-120 has merged (see plan.md § Status) — read the hook as merged, not as its plan described it.

## Read this before writing a line

`useTaskBarDrag` and `patchTaskDates` are described in
`plans/260824-workload-timeline-scheduling/phase-2-drag-hook.md` and `phase-1-store-seam.md`. Those are
a *plan*, not the merged code. Open the merged files first and work from what is actually there. If the
hook's signature differs from what this phase assumes, this phase adapts — the plan text does not win an
argument with the repository.

## Goal

Make an unscheduled bar draggable onto a date and resizable into a span, using the machinery the
scheduling work built, with one addition: a way to tell the hook where a bar that has no dates currently
sits.

## The one gap in the existing hook

The hook derives a bar's absolute pixel origin from
`getPositionFromDate(chart, task.start_date ?? task.target_date, 0)`. For a fully dateless task both are
`null`, so that expression yields `null` and every subsequent pixel calculation is nonsense — silently,
because `getPositionFromDate` will not throw on it.

Add an optional parameter:

```ts
useTaskBarDrag({
  task,
  chart,
  laneMarginLeft,
  disabled,
  onCommit,
  /**
   * The date column the bar is CURRENTLY drawn in, when the task's own dates
   * cannot supply one. Unscheduled bars are drawn at `start_date ?? today`
   * (`unscheduledAnchorDate`), which for a fully dateless task is a day that
   * appears nowhere on the task itself — so the hook cannot derive its own
   * origin and must be told.
   *
   * Defaults to `task.start_date ?? task.target_date` — i.e. every scheduled
   * bar behaves exactly as it did before this parameter existed.
   */
  anchorDate?: string,
})
```

Every existing call site keeps working untouched. Confirm that by leaving the scheduled-lane call site
alone entirely; if it needs an edit, the default is wrong.

## What each gesture writes

| Gesture | Result |
| --- | --- |
| `move` | Both dates set to the dropped day. A fully unscheduled task becomes a one-day task; a start-only task keeps its duration of one day and moves wholesale. |
| `resize-end` | `target_date` set to the dragged day. `start_date` is materialised at the anchor if the task has none — this is what turns a dateless task into a real span in a single gesture. |
| `resize-start` | Only meaningful once a target exists. On a bar with no target, treat the left handle as `move` rather than rendering a handle that writes a start with nothing to clamp it against. Clamp normally (`start <= target - 1 day`) in every other case. |

The commit itself is the existing path: `patchTaskDates` optimistically, `patchIssue` over the wire,
`rollbackTaskDates` plus an error toast on rejection. **Write no new write-path code in this phase** — if
you find yourself adding a service call, the scheduling plan's phase 4 already has one and you are
duplicating it.

## The repack is the acceptance test

Once `patchTaskDates` gives the task a `target_date`, three things must follow from code that already
exists, with nothing new written for any of them:

1. `selectUnscheduledTasks` stops returning it (it filters on `!target_date`).
2. `packTasksIntoLanes` starts returning it, so it appears as a normal solid bar in a scheduled lane.
3. If the swimlane had exactly 4 unscheduled tasks and one is now scheduled, the footer strip disappears
   — `hiddenCount` fell to 0.

The bar visibly changing from dashed to solid at the moment it lands is the whole feature working. If it
stays dashed after a successful drop, the block builder is not re-running — check that `patchTaskDates`
replaced `workloadData` with a new object rather than mutating in place (that is step 3 of its four
steps, and the reason it exists).

Note that the fourth of those tasks does **not** slide up into the freed row until the refetch lands, and
that is correct: the selection is a function of the response, not of the drag.

## Permission gate

Identical to the scheduled bars, evaluated **per bar** on that task's own `project_id`:

```ts
allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT,
  workspaceSlug, task.project_id)
```

When false: no handles, `cursor-pointer` not `cursor-grab`, `disabled` passed to the hook. The bar still
opens the peek panel, and it still renders — an unscheduled item the viewer cannot schedule is still an
item they should be able to see. Do not grey it further; it is already the most muted thing on the chart.

## Handles at this width

An unscheduled bar is `Math.max(dayWidth, MIN_BAR_WIDTH)` wide — 60px at Month and Quarter. The
scheduling plan's rule already covers this case: below roughly 24px of remaining body after two 6px
handles, render the right handle only. Follow it rather than restating it, and check the Quarter-zoom
case by hand, because that is the width where the rule actually binds.

## Manual checks

- Drag a fully dateless bar three columns right; it lands solid on that day, keeps its hours, and its
  swimlane's footer count drops by one.
- Drag a start-only bar; its start moves with it rather than staying behind.
- Right-resize a dateless bar across four columns; it becomes a four-day span, not a one-day bar at the
  far end.
- Click a bar without moving past the threshold; the peek panel opens as it did in phase 4.
- As a viewer with guest access to the bar's project; no handles, no drag, peek still opens.
- Reject the write (offline, or a stubbed 4xx); the bar returns to dashed at its anchor and a toast
  appears. A bar that stays solid after a failed write is the one outcome that must not happen.
