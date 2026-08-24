# Workload timeline — click to create, drag and resize to reschedule

**Created:** 2026-08-24
**Branch:** `feat/workload-timeline-scheduling`
**Plane:** [PLANE-120](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/4db1af20-6e05-4e0d-8cf3-56c4f281e41a) — parent, Infrastructure › Plane. Six phase sub-tasks PLANE-121 … PLANE-126, 15.5h total, all in Todo.
**Scope:** frontend only. One new action on `packages/workload-ext`'s store, a new drag hook plus
edits to three files under `apps/web/core/components/workload/timeline/`, and one new overlay
component. **No backend change, no new endpoint, no migration, no core-frontend edit.**

## Problem

The workload timeline renders per-assignee swimlanes of task bars but is entirely read-only. A
lead who spots an overloaded week has to leave the board, open each work item, and edit its dates
one at a time — the view that makes the problem visible cannot act on it. There is also no way to
put new work onto a member's lane from here at all.

Three affordances close that:

1. **Drag a bar sideways** → move the work item, keeping its duration.
2. **Drag a bar's left/right edge** → change its start or target date independently.
3. **Click empty space in a swimlane** → create a work item pre-dated to the click and
   pre-assigned to that swimlane's member.

## Prior art — what already exists, and the one thing that does not

Searched across `apps/web/core/components/gantt-chart/`, `apps/web/core/components/workload/`,
`apps/web/core/components/issues/`, and `packages/workload-ext/`.

| Capability                                           | Status                                         | Location                                                                                                                                                                                                                                       |
| ---------------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Per-block drag/move/resize state machine             | **exists**                                     | `gantt-chart/helpers/blockResizables/use-gantt-resizable.ts`                                                                                                                                                                                   |
| Left/right resize handles                            | **exists**                                     | `gantt-chart/helpers/blockResizables/{left,right}-resizable.tsx`                                                                                                                                                                               |
| Per-block enable predicates (`(blockId) => boolean`) | **exists**                                     | `gantt-chart/root.tsx:28-34`, resolved in `ce/components/gantt-chart/blocks/blocks-list.tsx`                                                                                                                                                   |
| Pixel ↔ date conversion                              | **exists**                                     | `gantt-chart/views/helpers.ts:73` `getDateFromPositionOnGantt`, `:120` `getPositionFromDate`                                                                                                                                                   |
| Click-empty-row → schedule an _undated_ block        | **exists, wrong shape**                        | `gantt-chart/helpers/add-block.tsx` — `BlockRow` only renders it when the block has **no** dates (`block-row.tsx:117`). Every workload lane block has dates, so it never appears, and it schedules an existing block rather than creating one. |
| Issue date write                                     | **exists**                                     | `services/issue/issue.service.ts:226` `patchIssue(slug, projectId, issueId, data)`                                                                                                                                                             |
| Prefilled create modal                               | **exists**                                     | `components/issues/issue-modal/modal.tsx` — `data`, `onSubmit`, `storeType`, `allowedProjectIds`                                                                                                                                               |
| Per-project permission check                         | **exists**                                     | `store/user/base-permissions.store.ts:191` — `allowPermissions(roles, PROJECT, slug, projectId)`                                                                                                                                               |
| Workload store: per-task mutation                    | **absent across `packages/workload-ext/src/`** | only `updateEstimate`/`deleteEstimate` (hours) and `resetCoverage` (drops everything) exist                                                                                                                                                    |
| Drag of an individual **task bar**                   | **absent**                                     | see the finding below                                                                                                                                                                                                                          |

### The finding that shapes the whole design

**A task bar is not a gantt block.** `blocks.ts:130` packs several non-overlapping tasks into one
`kind: "lane"` block, and `WorkloadTimelineChartBlock.tsx` positions each bar absolutely _inside_
that block's box. Core's `ChartDraggable` operates on `block.position`, so enabling
`enableBlockMove` would drag every bar in the lane together. Core's machinery is unreachable for
this feature not because it is missing, but because the unit it moves is the wrong one.

Lane packing is load-bearing: it is what turned a 49-task member from 49 rows into a handful
(commit #60). Abandoning it to reuse core's drag would undo that.

## Decisions (resolved)

| #   | Decision                                                                                                                                                                                                                                                                                                                                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | **Fork-owned per-bar drag**, in a new `useTaskBarDrag` hook under the fork's own timeline directory. Lane packing is kept; core's `ChartDraggable` stays off for lanes (`enableBlockMove`/`enableBlockLeftResize`/`enableBlockRightResize` remain `false`). Zero core-frontend edits.                                                                         |
| D2  | **Create opens core's `CreateUpdateIssueModal` unmodified**, prefilled with `start_date` / `target_date` from the click x-position and `assignee_ids` from the swimlane. No estimated-hours field is added here — that field is being added to the create form by separate work in flight; this plan must not touch the issue-modal form.                     |
| D3  | **Optimistic patch + background refetch.** A new `patchTaskDates` action rewrites the task's dates in `workloadData` so the bar stays where it was dropped, then clears `loadedRanges` and bumps `coverageVersion`; the timeline's existing `coverageVersion` effect refetches the viewport and `mergeWorkloadResponses` overwrites the affected period keys. |
| D4  | **Per-project `MEMBER`/`ADMIN`** gates each bar independently, keyed on that task's own `project_id`. A bar from a project the viewer only guests in renders with no handles and no drag cursor.                                                                                                                                                              |
| D5  | **Day snapping at every zoom.** `dayWidth` is 180 / 60 / 30 at week / month / quarter (`gantt-chart/data/index.ts:104,115,126`), so a one-day step is at worst 30px — draggable everywhere. No zoom is excluded.                                                                                                                                              |
| D6  | **A drag never navigates.** The bar is wrapped in a `ControlLink` (`WorkloadTaskLink`), so pointer-down starts a candidate drag and only a movement past a 4px threshold commits to it; below the threshold the click falls through to the peek panel unchanged.                                                                                              |
| D7  | **Duration is preserved on a move, and clamped on a resize.** A move shifts both dates by the same number of days. A resize cannot push start past target: the dragged edge stops one day short.                                                                                                                                                              |
| D8  | **A task with no `start_date`** (bar drawn from `target_date` alone) gets both dates written on a move, and gains a `start_date` on a left-resize. A task with no `target_date` is never drawn and is therefore never draggable.                                                                                                                              |
| D9  | **Repacking is deferred to drop.** During a drag the bar moves under a local CSS transform only; the store is patched on pointer-up, which is what re-runs `packTasksIntoLanes`. Patching per frame would make the bar jump lanes mid-drag.                                                                                                                   |
| D10 | **Failure rolls back.** A rejected `patchIssue` restores the pre-drag dates in the store and raises an error toast. The bar snapping back is the signal that the write did not land.                                                                                                                                                                          |
| D11 | **No `resetCoverage()` after a drag.** It nulls `workloadData` (`store.ts:248`), blanking the whole board — acceptable once on peek-panel close, unacceptable on every bar drag. Hence D3's narrower invalidation.                                                                                                                                            |

### Known limitation, stated rather than hidden

D3 refetches only what the viewport covers. Moving a task so that its hours land in a period
**outside** the current viewport leaves that period's heat cell stale until the next full
`resetCoverage` (a filter change, a zoom change, or a peek-panel close). The bar itself is always
correct; the heat cell off-screen may lag. Recomputing buckets client-side would mean
reimplementing `apps/api/plane/workload/aggregation.py` in TypeScript and keeping two
implementations of the same arithmetic in step — a worse trade than a bounded, documented lag.

## Phases

| Phase | File                                                       | Deliverable                                                     | Est. |
| ----- | ---------------------------------------------------------- | --------------------------------------------------------------- | ---- |
| 1     | [`phase-1-store-seam.md`](phase-1-store-seam.md)           | `patchTaskDates` + `rollbackTaskDates` on the workload store    | 2h   |
| 2     | [`phase-2-drag-hook.md`](phase-2-drag-hook.md)             | `useTaskBarDrag` — pointer math, snapping, thresholds, clamping | 3.5h |
| 3     | [`phase-3-bar-wiring.md`](phase-3-bar-wiring.md)           | Handles + drag wiring on the bars, per-project permission gate  | 3h   |
| 4     | [`phase-4-write-path.md`](phase-4-write-path.md)           | `patchIssue` call, optimistic commit, rollback, toasts          | 2h   |
| 5     | [`phase-5-click-to-create.md`](phase-5-click-to-create.md) | Empty-space click overlay + prefilled create modal              | 3h   |
| 6     | [`phase-6-verify-docs.md`](phase-6-verify-docs.md)         | Verify script, type-check, build, docs, propagation assessment  | 2h   |

**Total ~15.5h.** Critical path is 1 → 2 → 3 → 4. Phase 5 depends only on phase 3's overlay
plumbing; phase 6 closes.

## File ownership

Single-agent cook, sequential. Files touched:

| File                                                                           | Phase   |
| ------------------------------------------------------------------------------ | ------- |
| `packages/workload-ext/src/store.ts`                                           | 1       |
| `packages/workload-ext/verify-merge.mjs`                                       | 1, 6    |
| `apps/web/core/components/workload/timeline/useTaskBarDrag.ts` _(new)_         | 2       |
| `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`    | 3, 5    |
| `apps/web/core/components/workload/timeline/WorkloadTaskLink.tsx`              | 3       |
| `apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx`          | 4, 5    |
| `apps/web/core/components/workload/timeline/WorkloadCreateOverlay.tsx` _(new)_ | 5       |
| `packages/workload-ext/src/i18n.ts`                                            | 3, 4, 5 |
| `CLAUDE.md`, `docs/FORK.md`                                                    | 6       |

**Nothing under `apps/api/`, nothing under `apps/web/core/components/gantt-chart/`, nothing in
`apps/web/core/components/issues/issue-modal/`.** An edit landing in any of those means a decision
above was worked around rather than followed.

## Risk assessment

| Risk                                                                | L   | I   | Score | Mitigation                                                                                                                                                                 |
| ------------------------------------------------------------------- | --- | --- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Drag competes with `ControlLink`'s click → bar navigates mid-drag   | 4   | 4   | 16    | D6's 4px threshold plus `preventDefault` on the drag branch; phase 3 tests both a plain click and a 2px jitter click by hand                                               |
| Optimistic patch clobbered by an in-flight refetch that predates it | 3   | 4   | 12    | `patchTaskDates` bumps `coverageVersion`; `_fetchGap` already discards a response whose `requestedVersion` no longer matches (`store.ts:315`)                              |
| Bar jumps lanes mid-drag as packing re-runs                         | 4   | 2   | 8     | D9 — store patched on drop only                                                                                                                                            |
| Heat cells disagree with bars after a drag                          | 3   | 2   | 6     | Documented limitation above; viewport periods self-correct on the refetch                                                                                                  |
| Shared-assignee task patched on one row only                        | 2   | 4   | 8     | `patchTaskDates` iterates **every** row and patches each occurrence of the id — a work item with two assignees appears on two rows                                         |
| Guest drags work in a project they cannot edit                      | 2   | 5   | 10    | D4's per-project check, evaluated per bar, not per board                                                                                                                   |
| No frontend test harness exists to catch a regression               | 4   | 3   | 12    | Follow the `verify-merge.mjs` precedent: pure date math goes in a hand-runnable node script; pointer behaviour is verified manually against a written checklist in phase 6 |

## Verification bar

CI runs `pnpm check` (type-check) and `pnpm turbo run build --filter=web`; there is **no frontend
test job** in `.github/workflows/company-main-ci.yml`. Per phase:

- Pure functions (date arithmetic, clamping, snapping) get assertions in
  `packages/workload-ext/verify-merge.mjs`, run with
  `pnpm --filter @plane/workload-ext build && node verify-merge.mjs`.
- Pointer behaviour gets a written manual checklist in phase 6, executed before the PR is opened.
- Every phase ends green on `pnpm check`.

## Propagation

Per `CLAUDE.md`'s standing rule, assessed and found **not applicable**: this plan adds no endpoint,
no field, and no API behaviour. Rescheduling uses the existing `PATCH` issue endpoint (already
exposed as MCP `update_work_item`) and creation uses the existing issue-create path. No
`plane-mcp-server`, SDK, or docs change is owed. Phase 6 records this in `CLAUDE.md` rather than
leaving the absence of a propagation PR unexplained.
