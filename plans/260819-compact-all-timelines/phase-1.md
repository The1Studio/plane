# Phase 1 — Lane packing in core

**Goal:** one chart row holds every block whose dates do not overlap. Parent: [`plan.md`](plan.md).

## Ownership

- `apps/web/core/components/gantt-chart/helpers/lanes.ts` (new)
- `apps/web/ce/components/gantt-chart/blocks/blocks-list.tsx` — the BAR layer
- `apps/web/ce/components/gantt-chart/blocks/block-row-list.tsx` — the ROW-BACKGROUND layer
- `apps/web/core/components/gantt-chart/blocks/block-row.tsx`

**Note the `ce/` paths.** They are imported through the `@/plane-web/*` alias, which
`apps/web/tsconfig.json` maps to `./ce/*`. Grepping `core/` for `GanttChartBlocksList` finds only
the import, not the component.

## 0 — The chart is TWO overlaid row lists, not one

This is the single most important fact in this phase, and the easiest to miss. Inside one
positioned container (`chart/main-content.tsx`), five layers are stacked, and the first and last
are BOTH `blockIds.map`:

| Layer | Component                                  | Renders                                                                             |
| ----- | ------------------------------------------ | ----------------------------------------------------------------------------------- |
| 1     | `GanttChartRowList` (`block-row-list.tsx`) | one `BlockRow` per block — the row background, hover state, add-block affordance    |
| 2     | `TimelineDependencyPaths`                  | dependency arrows between rows                                                      |
| 3     | `TimelineDraggablePath`                    | the drag preview path                                                               |
| 4     | `GanttAdditionalLayers`                    | takes `blockCount={blockIds.length}`; a no-op stub in CE (`() => null`), real in EE |
| 5     | `GanttChartBlocksList` (`blocks-list.tsx`) | one `GanttChartBlock` per block — the bar itself                                    |

Layers 1 and 5 are independent maps over the same array, drawn on top of each other and kept in
register only because both produce the same number of rows in the same order. **Packing one and
not the other silently desynchronises them** — bars land on the wrong backgrounds, and nothing
errors. Both must consume the same lane list, produced once.

Layer 4's `blockCount` is a row count. It is inert in CE but wrong under packing; pass the lane
count so an EE build is not left with a mis-sized container.

## 1.1 — Move the packer into core (D5)

`packTasksIntoLanes` currently lives in `packages/workload-ext/src/merge.ts` (shipped in #43).
Core must not import a fork feature package, so it moves to
`components/gantt-chart/helpers/lanes.ts` and is generalised from `TWorkloadTask[]` to
`IGanttBlock[]`, keying off `block.start_date` / `block.target_date`.

The algorithm is unchanged and is already proven: greedy interval partitioning — sort by start,
place each block in the first lane whose last bar has ended. It uses exactly the maximum number
of blocks in flight at any instant, which is the lower bound on rows.

Two properties must survive the move, because both are pinned by existing checks that will be
ported alongside it (`packages/workload-ext/verify-merge.mjs`):

- **Adjacency counts as a collision.** A block with `start == target` occupies that whole day, so
  two touching bars must not share a row or they render fused.
- **The input array is never mutated.** It belongs to a MobX store; sorting it in place during a
  render mutates observable state.

Blocks with no `start_date` AND no `target_date` are not placed — `BlockRow` already drops them
unless `showAllBlocks`, and that behaviour is preserved by filtering before packing.

## 1.2 — Render one row per lane

`GanttChartBlocksList` maps `blockIds` → one `BlockRow` each today. It instead maps
`lanes` → one row each, and each row renders its blocks **absolutely positioned from the chart
origin**:

```tsx
<div className="relative w-max min-w-full" style={{ height: BLOCK_HEIGHT }}>
  {lane.map((block) => (
    <div className="absolute top-0" style={{ left: block.position.marginLeft, width: block.position.width }}>
      {blockToRender(block.data)}
    </div>
  ))}
</div>
```

This is simpler than the lane-relative maths #43 needed in workload: there, the lane itself was a
positioned _block_ so its children had to be offset against its own `marginLeft`. Here core owns
the row, the row spans the full chart width, and `position.marginLeft` is already an absolute
offset from the chart's start — so it can be used directly.

`BLOCK_HEIGHT` stays a single shared constant; rows remain uniform.

## 1.2b — Two things the packer must pin down

**Lane order.** Greedy packing emits lanes in creation order, which means lane 0 holds the
earliest-starting block. That is stable for a given input, but the input is `blockIds`, whose
order changes when the user re-sorts. Decide and document whether lanes re-pack on sort change
(simplest, rows visibly reshuffle) or whether packing is seeded by a stable key. Do not leave it
emergent.

**Blocks with no dates.** `BlockRow` today drops a block unless `showAllBlocks` is set
(`block-row.tsx`, the `!showAllBlocks && !(start_date && target_date)` guard). Packing must apply
the SAME rule before packing, not after, or `showAllBlocks: true` will produce lanes containing
unplaceable blocks with no position to render at.

## 1.3 — What must keep working

- **`RenderIfVisible` virtualisation is ALREADY on the chart rows** — `block-row-list.tsx` wraps
  each `BlockRow` in it, and `blocks/block.tsx` wraps each bar. It is not sidebar-only. So
  virtualisation survives Phase 2 for free; what changes is that the unit being virtualised
  becomes a LANE rather than a block, and a lane holding 30 bars is one unit. Keep the wrapper at
  the row level; do not wrap individual bars a second time.
- **The hidden-block affordance** (`block-row.tsx`, the arrow button that scrolls a
  scrolled-off block into view) is per-block and assumes one block per row. With several bars per
  row it either points at the first off-screen one or is dropped. Dropping it is acceptable here;
  say so explicitly rather than leaving it half-working.

## Success criteria

- `packBlocksIntoLanes` ported with its adjacency and no-mutation checks still passing.
- A timeline with N non-overlapping blocks renders 1 row, not N.
- A timeline with N mutually-overlapping blocks still renders N rows.
- `pnpm --filter web check:types` clean.
