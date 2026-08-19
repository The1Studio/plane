# Phase 2 — Remove the built-in sidebar

**Goal:** no timeline ships a block-list sidebar; the slot renders only what a consumer passes.
Depends on Phase 1. Parent: [`plan.md`](plan.md).

## Ownership

- `apps/web/core/components/gantt-chart/sidebar/**` (issues + modules block lists deleted)
- `apps/web/core/components/gantt-chart/chart/main-content.tsx`
- `apps/web/core/components/issues/issue-layouts/gantt/base-gantt-root.tsx`
- `apps/web/core/components/modules/gantt-chart/modules-list-layout.tsx`
- `apps/web/core/components/issues/issue-layouts/gantt/blocks.tsx`

## 2.1 — No flag (D1)

There is deliberately **no `showSidebar` boolean**. `sidebarToRender` becomes optional; when a
consumer passes nothing, `GanttChartSidebar` is not rendered at all and `SIDEBAR_WIDTH`
contributes zero. Issues, modules and epics pass nothing. Workload passes its swimlane content
and therefore still has one.

A flag would have been a second source of truth for the same fact — "is there sidebar content?" —
and the two would eventually disagree.

`IssuesSidebar` and `ModulesSidebar` (the per-block lists) are deleted outright rather than left
unreferenced.

## 2.2 — `SIDEBAR_WIDTH` is load-bearing in five places

Every one of these assumes the sidebar occupies the first `SIDEBAR_WIDTH` px of the scroll
container. With no sidebar the offset must become 0, and missing one leaves bars mispositioned by
360px:

| Site                                            | Use                                                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------ |
| `issue-layouts/gantt/blocks.tsx`                | `style={{ left: SIDEBAR_WIDTH }}` keeps the bar's label sticky past the sidebar      |
| `block-row.tsx`                                 | the hidden-block button's `left`                                                     |
| `block-row.tsx`                                 | `IntersectionObserver` `rootMargin: 0 0 0 -SIDEBAR_WIDTH`                            |
| `sidebar/root.tsx`                              | the sidebar's own width                                                              |
| `workload/timeline/WorkloadTimelineRoot.tsx`    | `syncViewport` derives the visible date range from `scrollLeft + SIDEBAR_WIDTH`      |
| `sidebar/gantt-dnd-HOC.tsx`, `sidebar/utils.ts` | reorder drag maths, dead once Phase 3 disables reorder — delete with the block lists |

The workload one is ours and is the easiest to miss: get it wrong and the viewport-driven loader
fetches the wrong range, which looks like a data bug rather than a layout one.

Prefer deriving the offset from whether sidebar content exists, in ONE place, over five
independent conditionals.

## 2.3 — Load-more becomes automatic (D4)

`loadMoreBlocks` / `canLoadMoreBlocks` are called from the sidebar today. Move the trigger to the
chart's existing `onScroll` in `main-content.tsx`, which already computes distance-to-end for
axis pagination — fire `loadMoreBlocks()` from the same place when `canLoadMoreBlocks`.

Debounce it. That handler runs on every scroll frame, and an undebounced call would issue a page
request per frame.

## 2.4 — Quick-add is dropped from Timeline (D4)

Remove the `quickAdd` prop plumbing from the gantt and the `quickAdd` construction in
`base-gantt-root.tsx`. Item creation remains on List, Board, Kanban, Calendar and Spreadsheet.

## Success criteria

- No timeline renders a block-list sidebar; workload still shows avatar + name + capacity badge.
- Bar labels sit flush at the chart's left edge — no 360px gap, no clipping.
- `grep -rn "SIDEBAR_WIDTH" apps/web` shows every remaining use is intentional and accounted for.
- Scrolling toward the end of a long project's Timeline pages in more items, once per page.
