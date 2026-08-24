# Phase 4 — drawing the bar, the spacer, and the overflow footer

**Owns:** `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`,
`apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx`,
`packages/workload-ext/src/i18n.ts`
**Estimate:** 2.5h
**Depends on:** phase 3

## Goal

Make the `kind: "unscheduled"` blocks visible, in a way no reader mistakes for scheduled work, and
switch the footer to reporting only what the cap hid.

## Chart side

A new branch in `WorkloadTimelineChartBlock.tsx`, placed **before** the `kind === "lane"` branch so the
early `if (!currentViewData) return null` guard is shared.

```tsx
if (data.kind === "unscheduled") {
  if (!currentViewData) return null;
  const block = getBlockById(data.id);
  const blockMarginLeft = block?.position?.marginLeft ?? 0;
  const dayWidth = currentViewData.data.dayWidth;
  const left = getPositionFromDate(currentViewData, data.anchorDate, 0) - blockMarginLeft;
  const width = Math.max(dayWidth, MIN_BAR_WIDTH);
  ...
}
```

Three points that are not obvious from the code:

- **`blockMarginLeft`, not `laneMarginLeft`.** The block spans the whole window (phase 3), so its own
  `marginLeft` is the pixel origin the absolute position must be reduced against — identical to the
  header branch, and NOT to the lane branch, whose block box starts at its first bar.
- **`Math.max(dayWidth, MIN_BAR_WIDTH)`, not `endPos - startPos`.** There is no end date to measure to.
  A one-day-wide bar is 180px at Week, 60px at Month, and 30px at Quarter — the last of which is below
  the floor that keeps the hours label from clipping its tail, which is exactly what `MIN_BAR_WIDTH`
  exists for (read its docstring before changing this line).
- **Reuse `MIN_BAR_WIDTH`; do not introduce a second constant.** Its whole rationale is about the hours
  label, and an unscheduled bar renders the same label.

### Styling (D7, D8)

```
border border-dashed border-tertiary bg-transparent text-tertiary
hover:bg-tertiary/10 hover:border-secondary
```

Deliberately not `bg-accent-primary/15` (scheduled) and not `bg-danger-subtle` (overdue). The dashed,
unfilled outline is the whole signal: a placeholder occupying a column, not a span covering it. An
unscheduled task is never `overdue` — the backend requires a non-null target for that flag — so there is
no red branch to write here.

Contents follow the lane branch's proven two-node shape: `<span className="min-w-0 flex-1 truncate">`
for the name, `<span className="shrink-0 tabular-nums">` for `{task.hours}h`. Do **not** collapse them
into one node; the comment in the lane branch explains why the estimate loses the ellipsis fight. Drop
the name at Quarter zoom on the same `isQuarter` rule the lane branch uses.

### Title

```
`${task.identifier} ${task.name} · ${task.hours}h · ` + wlt("timeline.unscheduled_bar_title")
```

with the string reading, in full:

> Unscheduled — these hours are not counted in any capacity cell until the work item has a target date.

That sentence is the entire mitigation for D10. It is the only place a reader learns why the bar's `4h`
does not appear in the heat cell directly beneath it, so it must say both halves: what the bar is, and
what it is not counted in. Keep the split-assignee clause the lane branch appends when
`assignee_count > 1` — a shared unscheduled task has the same "why does this say 4h of an 8h item"
problem.

### Click

Wrap in `WorkloadTaskLink` exactly as the lane branch does, so the bar opens the peek panel. That is the
one place an unscheduled item's dates can be set before phase 3 lands, and it must work at the end of
this phase on its own.

## Sidebar side

`WorkloadTimelineSidebarRow.tsx` gets a branch for `data.kind === "unscheduled"` returning a bare
`<SidebarCell key={blockId} />`.

**This is not optional and it is not decorative.** The lane branch's comment already spells out the
consequence of skipping a cell: the chart body lays out one `BlockRow` per blockId at a fixed
`BLOCK_HEIGHT`, so a block that renders no sidebar cell shortens the sidebar column by 44px and slides
every row below it out of alignment with its own bars, an error that accumulates down the page. Copy
that reasoning into the new branch — a future reader deleting an "empty" cell is exactly the failure it
guards against.

## Footer

Replace the count:

```tsx
// Before
const unscheduledCount = row.tasks.filter((t) => !t.target_date).length;
{unscheduledCount > 0 && <span>{wlt("timeline.unscheduled_count", { count: unscheduledCount })}</span>}

// After
{data.unscheduledHidden > 0 && (
  <span>{wlt("timeline.unscheduled_more", { count: data.unscheduledHidden })}</span>
)}
```

Read the number from the block (phase 3 put it there); do not recompute it from `row.tasks`. Recomputing
means restating the cap in a second place, and the two will drift the first time the cap changes.

`timeline.unscheduled_count` becomes unreferenced. **Delete it** rather than leaving it — a string that
says `Unscheduled (30)` sitting in the table is an invitation to re-introduce the double-count. Grep for
the key across `apps/web/` and `packages/` before removing it; the matrix's separate
`matrix.unscheduled` is a different key and stays.

## Strings

In `packages/workload-ext/src/i18n.ts`:

| Key | Value |
| --- | --- |
| `timeline.unscheduled_more` | `Unscheduled ({count} more)` |
| `timeline.unscheduled_bar_title` | `Unscheduled — these hours are not counted in any capacity cell until the work item has a target date.` |

Removed: `timeline.unscheduled_count`.

## Manual check before calling the phase done

Open the timeline on a workspace that has all three, in one swimlane if possible, and look at them
together:

1. An unscheduled bar, 2. a bar whose target date *is* today, 3. an overdue bar.

The first must be distinguishable from the second at a glance, without hovering. If it is not, the
styling is wrong regardless of what the code says. Then confirm: a member with 2 unscheduled tasks shows
2 bars and **no** footer strip; a member with 30 shows 3 bars and `Unscheduled (27 more)`; a collapsed
member shows neither.
