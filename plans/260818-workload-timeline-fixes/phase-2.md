# Phase 2 — Single time control

**Goal:** one visible time-range control that changes both the data bucketing and the axis zoom.
Depends on Phase 1. Parent: [`plan.md`](plan.md).

## Ownership

- `packages/workload-ext/src/WorkloadToolbar.tsx`
- `apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx`
- `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx`

**No core edit** (D3). `GanttChartHeader` keeps rendering its own `Week/Month/Quarter` + `Today` +
fullscreen row; we adopt it instead of hiding it.

## 2.1 — Delete the toolbar tabs

Remove the `Tabs` block (`WorkloadToolbar.tsx:118-133`), the `GRANULARITIES` table, the `Tabs`
import and `handleGranularityChange`. The date-range picker, member/project filters, state-group
chips, over-capacity switch and settings readout all stay.

## 2.2 — Bind `currentView` -> `granularity`

In `WorkloadTimelineRoot`, one mapping table and one `reaction`:

```ts
const VIEW_TO_GRANULARITY: Record<TGanttViews, TWorkloadGranularity> = { week: "day", month: "week", quarter: "month" };
const GRANULARITY_TO_VIEW: Record<TWorkloadGranularity, TGanttViews> = { day: "week", week: "month", month: "quarter" };
```

The pairing is by **column resolution**, not by label: `VIEWS_LIST`
(`gantt-chart/data/index.ts:75-107`) gives `week` a `dayWidth` of 60 (day columns, day labels),
`month` 20, `quarter` 5 — so gantt-`week` is the only view that can legibly host per-day heat cells,
and it is the view the reference screenshot is in.

```ts
useEffect(
  () =>
    reaction(
      () => timelineStore.currentView,
      (view) => {
        const next = VIEW_TO_GRANULARITY[view];
        if (next === store.granularity) return; // loop guard
        store.setGranularity(next);
        const { from, to } = clampDateRange(store.dateFrom, store.dateTo, next, "from");
        store.setDateRange(from, to); // see 2.3
        store.fetchWorkload(workspaceSlug);
      }
    ),
  [timelineStore, store, workspaceSlug]
);
```

`workspaceSlug` has to reach the timeline root — add it as a prop from the route page rather than
re-reading `useParams` (the page already has it).

## 2.3 — Re-clamp the range on every granularity change

`MAX_SPAN_DAYS` is `{day: 92, week: 366, month: 730}` (`dateRange.ts:11-15`, mirroring
`views.py:35`). Zooming out to `quarter` then back to `week` leaves a range far longer than 92 days,
and the API answers **400**, not a truncated result. The `clampDateRange` call above is therefore
load-bearing, not defensive — anchor `"from"` so the window keeps its start and gives up its tail.

Surface the clamp: when it actually shortened the range the picker will visibly jump. That is
correct and better than a 400, but it must not be silent — Phase 5 adds a one-line hint under the
toolbar when `daysBetween` changed.

## 2.4 — Agree from the first frame

`BaseTimeLineStore` defaults `currentView = "week"` (`ce/store/timeline/base-timeline.store.ts:78`)
while the workload store defaults `granularity = "week"` (`store.ts:93`) — i.e. they start
_disagreeing_ (gantt-week means day buckets). On mount, push the store's granularity into the
timeline store via `GRANULARITY_TO_VIEW` before the first fetch, so the axis and the data always
describe the same thing.

## Success criteria

- Only one `Week/Month/Quarter` control renders on the page.
- Switching it issues exactly one refetch and re-zooms the axis in the same interaction.
- `quarter -> week` on a 700-day range produces a 92-day range and a 200, never a 400.
- No refetch loop: switching views twice issues two requests, not four.
