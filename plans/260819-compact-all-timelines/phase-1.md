# Phase 1 — Lane packing in core

**Goal:** one chart row holds every block whose dates do not overlap. Parent: [`plan.md`](plan.md).

## Ownership

- `apps/web/core/components/gantt-chart/helpers/lanes.ts` (new)
- `apps/web/ce/components/gantt-chart/blocks/blocks-list.tsx`
- `apps/web/core/components/gantt-chart/blocks/block-row.tsx`

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

## 1.3 — What must keep working

- **`RenderIfVisible` virtualisation** currently wraps sidebar rows. With the sidebar gone
  (Phase 2) the chart rows are what needs virtualising, or a 2,000-block project will render
  every bar. Either wrap the lane rows or accept the cost — measure before deciding, and say
  which was chosen.
- **The hidden-block affordance** (`block-row.tsx`, the arrow button that scrolls a
  scrolled-off block into view) is per-block and assumes one block per row. With several bars per
  row it either points at the first off-screen one or is dropped. Dropping it is acceptable here;
  say so explicitly rather than leaving it half-working.

## Success criteria

- `packBlocksIntoLanes` ported with its adjacency and no-mutation checks still passing.
- A timeline with N non-overlapping blocks renders 1 row, not N.
- A timeline with N mutually-overlapping blocks still renders N rows.
- `pnpm --filter web check:types` clean.
