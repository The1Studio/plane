# Phase 3 — Row structure: task labels, footer block, weekly badge

**Goal:** make the swimlane match the reference (`image.png`) — a weekly badge, a heat cell on every
visible column, a labelled task row, and an Unscheduled/Overdue footer. Depends on Phase 1.
Parent: [`plan.md`](plan.md).

## Ownership

- `apps/web/core/components/workload/timeline/types.ts`
- `apps/web/core/components/workload/timeline/blocks.ts`
- `apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx`
- `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`
- `packages/workload-ext/src/WorkloadToolbar.tsx` (over-capacity filter semantics only)

## 3.1 — A third block kind: `footer` (D4)

`BLOCK_HEIGHT` is 44px and is hardcoded inside core's `blocks/block-row.tsx:88`. Rather than edit
core to give the header row three lines, model the reference's per-person footer strip as its own
block — every row stays 44px and the fork surface stays zero.

`types.ts` gains `TWorkloadFooterBlockData` (`kind: "footer"`, `assigneeId`, `row`) and the union
grows a third member. `blocks.ts` emits, per assignee:

```
[ header, task, task, …, footer ]
```

The footer carries the same `start_date` / `target_date` as the header so `BlockRow`'s
`showAllBlocks` guard (`block-row.tsx:76` — a block with no dates is dropped) keeps it alive; its
chart-side render is an empty div.

Collapsing hides that assignee's `task` **and** `footer` blocks and keeps the `header` — same rule
as today, one more kind to skip.

## 3.2 — Sidebar: header row

Replace the window-total badge (`WorkloadTimelineSidebarRow.tsx:73`, `:110`) with the weekly one:

```ts
const focusWeek = focusWeekKey(store.workloadData, weekStartDay); // new pure helper
const used = row.weekly_buckets?.[focusWeek] ?? 0;
const capacity = row.weekly_capacity ?? 0;
```

`focusWeekKey` lives beside `blocks.ts` and mirrors `period_key(d, "week", week_start_day)`: the
week containing today, clamped into `[date_from, date_to]` — if today is after the window, the last
week in it; if before, the first. Render the week it refers to as a `title` so `41h/40h` is never
ambiguous.

The second line keeps the unscheduled/overdue counts **only** until 3.3 moves them; after that the
header line is avatar + name + badge + chevron alone, as in the reference.

Tint: `used > capacity` (D6), not `row.total_over`.

## 3.3 — Sidebar: task row and footer row

- **Task row** — replaces the `null` spacer (`:62-70`) with `IssueIdentifier`-style
  `identifier` + truncated `name`, right-aligned `hours`. Left-padded one step past the header so
  the swimlane reads as a tree. This element is Phase 4's click target; ship it here as inert text
  and let Phase 4 wrap it — that keeps the two phases' diffs disjoint.
- **Footer row** — `Unscheduled (N)` / `Overdue (N)` / `showing first N of M`, each rendered only
  when non-zero, styled as the reference's muted strip. Counts move here verbatim from the header's
  current second line.

## 3.4 — Heat cells on every column

`WorkloadTimelineChartBlock` already maps `data.periods` (`:63`) and reads
`row.buckets[period] ?? 0` — after Phase 1's window fill it will iterate every visible period and
naturally emit the reference's `0h` columns. Two adjustments:

- render `0h` instead of `""` when the period is inside the window (currently `hours > 0 ? … : ""`),
  so an empty column is visibly _zero_ rather than visibly _missing_;
- keep the existing `title` tooltip (`"<period>: Nh / Nh"`) — it is now the per-period detail that
  the weekly badge no longer shows.

At gantt-`week` (granularity `day`, after Phase 2) this is exactly the reference's per-day strip.

## 3.5 — "Over capacity only" filter (D6)

`WorkloadToolbar`'s switch is a client-side row filter. Repoint it from `row.total_over` to
"any entry in `weekly_buckets` exceeds `weekly_capacity`". A member who is 60h in one week and idle
the next must still match — the window total would have hidden them.

## Success criteria

- The badge reads `NNh/40h` against the workspace's weekly max, and its tooltip names the week.
- Every visible column has a cell; empty ones read `0h`.
- Each swimlane ends with a footer row; collapsing hides the tasks and the footer, not the header.
- Task rows show `PROJ-12  Set up map 3`.
- The axis stays aligned across members with any mix of collapsed and expanded swimlanes.
