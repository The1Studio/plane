# Phase 3 — Disable per-block interactions

**Goal:** switch off every interaction that assumes one bar per row, without deleting the code
that implements them. Depends on Phase 1. Parent: [`plan.md`](plan.md).

## Ownership

- `apps/web/core/components/issues/issue-layouts/gantt/base-gantt-root.tsx`
- `apps/web/core/components/modules/gantt-chart/modules-list-layout.tsx`

## 3.1 — What gets switched off, and why each one breaks

| Prop                                               | Today                                     | Why packing breaks it                                                                                       |
| -------------------------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `enableBlockMove`                                  | `isAllowed`                               | `ChartDraggable` moves _the row's_ block; with several bars per row it has no way to know which was grabbed |
| `enableBlockLeftResize` / `enableBlockRightResize` | `isAllowed`                               | Same — the resize handles are positioned per row, not per bar                                               |
| `enableReorder`                                    | `isAllowed` + `order_by === "sort_order"` | Reordering means dragging a row to a new index; a lane is not an item, so there is nothing to reorder       |
| `enableSelection`                                  | bulk-ops flag                             | Selection is keyed by row; a row is now several items                                                       |
| `enableDependency`                                 | on (issues)                               | Dependency arrows are drawn between row centres; with packing, two dependent items may share a row          |
| `enableAddBlock`                                   | `isAllowed`                               | The add affordance appears on an empty row, which no longer maps to one item                                |

All become `false`.

**Two sibling layers keep rendering regardless of these props** and must be checked, not assumed
(`chart/main-content.tsx` renders them unconditionally, between the row and bar layers):
`TimelineDependencyPaths` and `TimelineDraggablePath`. Setting `enableDependency={false}` stops
the _interaction_; confirm it also stops the _paths_ being drawn, or a packed board will show
arrows between rows that no longer correspond to single items. If they render unconditionally,
gate them here.

**The implementing components are NOT deleted** — `ChartDraggable`, the
resizables, the dependency path layer and the multi-select group stay in the tree, unreferenced by
these consumers, because [`later.md`](later.md) restores them.

## 3.2 — Say it out loud

This is a **user-facing regression that ships to production on merge**. Dragging a bar to
reschedule, and dragging its edge to change duration, are the two things people most often do on
a Timeline, and both stop working.

Do not bury it in a changelog line. The PR description leads with it, and someone who uses
Timeline daily should be told before merge, not after.

If that is not acceptable, this phase is the one to reconsider — and without it, packing cannot
land on the issue gantt at all.

## Success criteria

- No drag, resize, reorder, dependency arrow or bulk-select on any timeline.
- The components implementing them still compile and are still exported.
- `grep -rn "enableBlockMove\|enableDependency" apps/web` shows only `false` at every call site.
