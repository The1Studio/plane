# Compact all timelines — lane packing, no built-in sidebar

Generalises the workload timeline's row packing to every Plane timeline, and removes the
block-list sidebar that made packing impossible.

Prior art: `plans/260818-workload-timeline-fixes/` (workload-only packing, shipped in #43).

## The problem

Core's gantt renders **one row per block**. `blockIds.map` drives the chart rows
(`blocks-list.tsx`) AND the sidebar rows (`sidebar/issues/sidebar.tsx`,
`sidebar/modules/sidebar.tsx`) in 1:1 index alignment, so a timeline is exactly as tall as it
has items — 200 work items is 200 rows, almost all of them mostly empty.

Two things block packing, and they are why #43 could only do workload:

1. **The sidebar's 1:1 mapping.** Pack N blocks into one row and the sidebar can no longer name
   that row.
2. **Per-block interactions.** `block.tsx` / `block-row.tsx` own drag-to-reschedule, resize,
   dependency arrows, reorder and bulk-select, all assuming one bar per row.

Workload sidestepped both: it has every interaction disabled and owns its own renderers.

## Decisions

- **D1 — the built-in sidebar is removed from every timeline, with no opt-in flag.** Core stops
  shipping `IssuesSidebar` / `ModulesSidebar` block lists. The sidebar _slot_ survives and
  renders only what a consumer passes, so there is no `showSidebar` boolean to get wrong: pass
  nothing (issues, modules, epics) and there is no sidebar; pass content (workload) and there is.
- **D2 — workload's sidebar carries swimlane identity only.** Avatar, member name, capacity
  badge. NOT a work-item list: the per-lane labels added in #43 (`PROJ-12` / `N items`) are
  removed, so lane rows become blank spacers that keep vertical alignment. Bars carry item
  identity, as they already do.
- **D3 — per-block interactions are DISABLED, not reworked.** Drag-to-reschedule, resize,
  dependency arrows, reorder and bulk-select are switched off on every timeline for this change.
  Restoring them on packed rows is [`later.md`](later.md), deliberately out of scope here.
- **D4 — load-more becomes automatic; quick-add is dropped from Timeline.** Both live inside the
  sidebar today. Paging moves to the chart's existing `onScroll` hook; item creation stays
  available on every other layout.
- **D5 — packing is core-owned.** The packer moves from `packages/workload-ext` into
  `components/gantt-chart/`, because core cannot depend on a fork feature package. Workload
  imports it back from core.

## What this costs — read before approving

**This is the deepest core divergence in the fork so far.** It rewrites the row model of
`gantt-chart/`, a directory upstream actively develops. Every future rebase will conflict here,
and unlike the seven touch-points these conflicts are _semantic_ — upstream changing how blocks
render will not merge cleanly into a lane model. `docs/FORK.md` gains its largest exception entry.

**Users lose drag-to-reschedule on Timeline** (D3). Today an issue bar can be dragged to move its
dates and resized to change duration; after this it cannot, until the follow-up lands. This
deploys to production on merge — the same day it is approved.

**Users lose the issue list beside the chart** (D1). Scanning "what work exists" from Timeline
becomes scanning bars rather than reading a column.

If either is unacceptable, the alternative is to compact ONLY timelines that already have
interactions disabled, which is close to what #43 already shipped.

## Phases

| Phase             | Title                               | Depends on       |
| ----------------- | ----------------------------------- | ---------------- |
| [1](phase-1.md)   | Lane packing in core                | —                |
| [2](phase-2.md)   | Remove the built-in sidebar         | 1                |
| [3](phase-3.md)   | Disable per-block interactions      | 1                |
| [4](phase-4.md)   | Workload adopts the core packer     | 1, 2             |
| [5](phase-5.md)   | Verification, FORK.md, propagation  | 2, 3, 4          |
| [later](later.md) | Restore interactions on packed rows | ships separately |

## Success criteria

- A project Timeline with 200 work items renders as many rows as its peak concurrency, not 200.
- No timeline renders a block-list sidebar; workload still shows avatar + name + capacity badge.
- Scrolling toward the end of the chart pages in more work items with no button.
- `pnpm --filter web check:types|format|lint` clean; `pytest plane/workload` green;
  `node packages/workload-ext/verify-merge.mjs` green.
- A named human has confirmed on screen: packed rows do not overlap, bars are still clickable,
  and the workload board still aligns. None of this is verifiable from here.
