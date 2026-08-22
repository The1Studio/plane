# Phase 1 — Remove the lane labels from the timeline sidebar

**Effort:** S (~0.5h) · **Depends on:** nothing · **Blocks:** Phase 2 (shared file)

## Goal

The left sidebar of the workspace workload timeline currently labels every
`kind: "lane"` row with either the lane's single task identifier
(`CODEBASE-131`) or, when the lane packs several non-overlapping tasks, a count
(`12 items`, `4 items`). Remove those labels. The lane's sidebar cell becomes
blank.

The `Unscheduled (N)` / `Overdue (N)` / `showing first N` strip that renders
directly beneath a member's lanes is a **different block kind** (`footer`) and
must be left exactly as it is. It is the row the user explicitly asked to keep.

## Ownership

```
apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx
apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx   # comment only
```

No other file is touched in this phase.

## Steps

1. In `WorkloadTimelineSidebarRow.tsx`, replace the body of the
   `data.kind === "lane"` branch so it renders an empty cell:

   ```tsx
   if (data.kind === "lane") {
     // The bars themselves carry the identifier, name and hours; a sidebar
     // label duplicated that and, for a packed lane, could only manage a
     // meaningless "N items". The cell stays (at BLOCK_HEIGHT) purely to keep
     // the sidebar column in step with the chart body, which stacks one
     // BlockRow per blockId.
     return <SidebarCell key={blockId} />;
   }
   ```

   The `SidebarCell` wrapper **must** survive — it is what supplies the
   `height: ${BLOCK_HEIGHT}px` style. Deleting the whole branch, or returning
   `null`, would shorten the sidebar column and slide every subsequent row out
   of alignment with its chart row.

   `SidebarCell`'s `children` prop is currently required
   (`children: React.ReactNode`); make it optional so an empty cell type-checks.

2. Update the file's header comment. The three-kind list currently reads:

   ```
   //   task   — work-item identifier + name (the click target for the peek panel)
   ```

   That line is now wrong twice over (the kind is `lane`, not `task`, and it no
   longer renders anything). Replace it with a line saying the lane cell is a
   deliberate blank spacer and why, pointing at the bars as the label carrier.

3. Update the stale cross-reference in `WorkloadTimelineChartBlock.tsx`
   (~line 126, inside the lane bar's JSX comment). It currently claims the
   identifier "stays in the `title` above, and in the sidebar cell for a
   single-task lane." The second clause is no longer true — drop it, leaving the
   `title` as the sole place the identifier survives.

4. Check whether `TWorkloadLaneBlockData.name` (set to `laneTasks[0].name` in
   `blocks.ts`) still has a consumer. It is part of the shape core's gantt
   primitives read, so **leave the field in place** even if this component no
   longer renders it — do not remove it as "dead" without grepping core's
   gantt-chart directory for `block.name` / `data.name` usage first.

## Success criteria

- The workload timeline sidebar shows **no** `N items` and **no** bare
  work-item identifier on any lane row, at any zoom.
- The `Unscheduled (N)` strip still renders, with its count unchanged.
- Every member's task bars still sit on the same visual row as that member's
  sidebar cell — no vertical drift accumulating down the page. Verify against a
  member with several lanes (`tratt`, `anhtv`, or `hieulv` in the reference
  screenshot).
- `pnpm --filter web typecheck` (or the repo's equivalent — check `package.json`
  scripts) passes with no new errors.
- No comment in either edited file still describes a lane sidebar label.
