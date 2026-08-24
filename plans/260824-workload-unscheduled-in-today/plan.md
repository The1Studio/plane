# Workload timeline — surface the work and the people it currently hides

**Created:** 2026-08-24
**Branch:** `feat/workload-unscheduled-today`
**Plane:** [PLANE-144](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/a1ac4459-51bc-45a7-ad89-23ae3dcb57e8) — parent, Infrastructure › Plane. Six phase sub-tasks PLANE-145 … PLANE-150, 13.5h total, all in Todo.
**Scope:** one fork-owned Django app (`plane/workload/service.py`), one pure selector in
`packages/workload-ext`, a new block kind and its render/drag wiring under
`apps/web/core/components/workload/timeline/`. **No core model change, no migration, no
core-frontend edit.** It is no longer frontend-only — see § Status.

## Status — PLANE-120 has merged; nothing is held

An earlier revision of this section held phases 3–6 behind
`plans/260824-workload-timeline-scheduling/` (PLANE-120). **That plan merged to `company-main` on
2026-08-24** — `2c0ecb2001` (#69) plus follow-ups `b8b6fe2f72` (#71), `f557be1f0c` (#72) and
`c2fa46e976` (#73). `useTaskBarDrag.ts`, `WorkloadCreateOverlay.tsx` and the store's
`patchTaskDates` are all present, so the dependency phase 5 was waiting on is satisfied and no
phase in this plan is blocked.

Phase 5 still opens the merged hook and works from what is actually there rather than from the
other plan's description of it — four commits of follow-up fixes landed after the original one,
and the signature this plan assumed was never a fact about the repository.

Phases **1–2 shipped first**, on `feat/workload-member-rows`. They touch no file the scheduling
work touched, which is why they were able to run ahead of it while it was still open.

## Problem

Two different things are invisible on the workload timeline, and both are invisible in the same
way — the reader cannot tell the difference between "nothing there" and "not shown".

**Unscheduled work.** A work item with an estimate but no target date is filtered out of the bars by
`packTasksIntoLanes` (`packages/workload-ext/src/merge.ts:208`) and survives only as a number in the
swimlane footer, `Unscheduled (30)`. The reader sees that a member carries thirty unplanned items and
cannot see what any of them are, how big they are, or act on one without leaving the board.

**Members with no work.** `compute_workload` derives its rows from the estimates it just summed
(`service.py:534`), so a member with no assigned work item — or with work items nobody estimated —
has no row at all. The board answers "who is overloaded" and cannot answer "who is free", which is
the other half of the question anyone opens a workload view to ask.

## Prior art — what already exists, and the two gaps

Searched `apps/api/plane/workload/`, `packages/workload-ext/src/`,
`apps/web/core/components/workload/`, and `apps/web/core/components/gantt-chart/`.

| Capability                                                                | Status                                                                                  | Location                                                                                                                                       |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Unscheduled tasks present in the API response                             | **exists**                                                                              | `service.py:469` — `if b or target is None` keeps a null-target task in `tasks[]` **regardless of the requested window**                       |
| Per-task hours, name, identifier, project for an unscheduled task         | **exists**                                                                              | same assembly; only the two date fields differ                                                                                                 |
| A membership predicate for "who may carry work here"                      | **exists**                                                                              | `_resolve_owners` (`service.py:222`) — active `ProjectMember`, non-bot, not soft-deleted                                                       |
| Per-row capacity independent of that row's load                           | **exists**                                                                              | `capacity_buckets` is computed once for the window and shared by every row (`service.py:540`) — an empty row already has a correct denominator |
| A block kind spanning the whole window with children positioned inside it | **exists**                                                                              | header + footer blocks, `blocks.ts:120-125`                                                                                                    |
| Absolute date → pixel conversion                                          | **exists**                                                                              | `gantt-chart/views` `getPositionFromDate`                                                                                                      |
| Empty sidebar spacer cell for a chart-only row                            | **exists**                                                                              | `WorkloadTimelineSidebarRow.tsx` lane branch                                                                                                   |
| Per-bar drag / resize / date write                                        | **exists** (PLANE-120, merged)                                                          | `useTaskBarDrag.ts`, `patchTaskDates`                                                                                                          |
| A row for an owner with no estimate                                       | **absent across `apps/api/plane/workload/`**                                            | gap 1 — `owner_ids` is a union of three estimate-keyed maps                                                                                    |
| Any rendering of a task with `target_date === null`                       | **absent across `packages/workload-ext/src/` and `apps/web/core/components/workload/`** | gap 2                                                                                                                                          |

For the unscheduled half, the data is already on the client and nothing needs fetching. For the
member half, the predicate already exists and only the row set needs widening.

## Decisions (resolved)

### Members with no work (phases 1–2)

| #   | Decision                                                                                                                                                                                                                                                                                                                                                                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D11 | **Membership = active, non-bot `ProjectMember` of the projects in the resolved scope** — the same predicate `_resolve_owners` already applies to decide who may be an assignee. A member gets a lane if and only if they could have been assigned work this request can see. Deliberately not `WorkspaceMember`: a member with no in-scope project would get a lane nothing could ever fill. |
| D12 | **Always on. No `include_empty_members` parameter.** This is a response-shape change for every existing `get_workload` consumer, which is why phase 6 propagates it rather than treating it as internal.                                                                                                                                                                                     |
| D13 | **Ordering unchanged** — `Unassigned` pinned first, then ascending by `assignee_name`, case-insensitively. Empty and loaded members interleave. The current sort exists because ranking by load re-ordered the list on every estimate change; grouping empties would reintroduce exactly that (a member moves the moment they are given work).                                               |
| D14 | **One rule covers both invisibilities.** Driving rows off the member list gives a lane to a member with zero assigned items _and_ to one whose items are all unestimated, with no second query and no special case — because from the reader's side the two are the same absence.                                                                                                            |
| D15 | **The assignee filter narrows empty rows too.** `assignee_filter` is applied per-issue-owner and never touches `owner_ids`, so without this, filtering to one person would leave every other member's empty lane on screen.                                                                                                                                                                  |
| D16 | **The empty-state overlay switches from counting rows to counting work.** Once every member has a row, `rows.length > 0` is true on a completely empty board and the `no_data_in_range` message becomes unreachable. See phase 2 — this is a consequence of D12, not an optional polish.                                                                                                     |

### Unscheduled work (phases 3–6)

| #   | Decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | **A new `kind: "unscheduled"` block, one task per block.** The original rationale — that a lane's box is `min(start)..max(target)` and too narrow — **was already stale when this shipped**: PLANE-120 widened lane boxes to span the whole window so they could host the click-to-create surface. Two reasons survive, both about the lane RENDERER: it positions a bar's right edge with `getPositionFromDate(chart, task.target_date!, dayWidth)`, which an unscheduled task cannot satisfy; and a lane block _is_ the create surface, whose job is to be empty.                                                                                                                           |
| D2  | **One bar per 44px row, anchored to its own date.** Bars are never laid side by side. With drag enabled (D6) a bar's x-position must mean a date everywhere on the chart, and a parked bar two columns right of today would claim a date it does not have.                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| D3  | **Anchor = `start_date ?? today`.** A task with a start but no target is unscheduled by today's definition, and it already carries a date the reader chose; anchoring it at its own start is more truthful than moving it to today.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| D4  | **Capped at 3 rows per swimlane** (`MAX_UNSCHEDULED_LANES`), taking the first three in server order — which `service.py:305` already sorts by `(start is None, start, target is None, target)`, so the three shown have the earliest starts and are stable across refetches.                                                                                                                                                                                                                                                                                                                                                                                                                  |
| D5  | **The footer reports only the overflow** — `Unscheduled (27 more)`, not the total. The other three are on screen; repeating them in a count invites the reader to add. The strip vanishes when everything fits.                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| D6  | **Draggable and resizable**, gated by the same per-project `MEMBER`/`ADMIN` check the scheduled bars use. **Implemented with no change to `useTaskBarDrag` at all** — the plan called for a new `anchorDate` parameter, but the renderer hands the hook a SYNTHETIC one-day task at the anchor instead, so the drag, resize, permission gate and label ladder are reused verbatim rather than growing a null-date branch through three layers. Only the dates are synthetic; `id`/`project_id` are real, so the commit patches the right issue and the rollback snapshot — read from the store — restores the true nulls. **Supersedes D8 of the scheduling plan**, rewritten in place there. |
| D7  | **Dashed outline, no fill.** A solid bar in today's column reads as "due today", a claim the data does not make.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| D8  | **Hours shown, muted, with the disclaimer in the hover title.** The estimate is the number this view exists for; hiding it to avoid a misreading costs more than it saves.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| D9  | **Anchored to today's real column, not pinned to the viewport.** Pan away and the bars scroll off like every other bar; the footer count still reports them.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| D10 | **Nothing is added to any heat cell.** The backend routes an unscheduled estimate to the separate `unscheduled` bucket. Adding the hours client-side would mean reimplementing `aggregation.py` in TypeScript, and would make a bar's hours vanish from the cell the moment it was scheduled for real.                                                                                                                                                                                                                                                                                                                                                                                        |

### Known limitations, stated rather than hidden

**The truncation cap drops unscheduled work first.** `_task_sort_key` sorts null dates last and
`tasks` is cut at `WORKLOAD_MAX_TASKS_PER_ASSIGNEE = 200`, so a member with more than 200 estimated
items loses their unscheduled tasks from the payload before this plan can draw any. Raising
unscheduled work above dated work in the cap is a backend decision with its own trade-off and
belongs in its own change.

**A bar's hours are in no capacity cell.** By D10, deliberately. The hover title says so.

**A long member list makes a long board.** D12 ships empty rows unconditionally, so a workspace with
many members and few active ones renders many one-line lanes. Collapse already defaults to collapsed
at Month and Quarter zoom, and an empty member is a single header line at every zoom, so the cost is
one 44px line per member — but on a large workspace that is a real amount of scrolling, and it is
the price of the question the feature answers.

## Phases

| Phase | File                                                               | Deliverable                                                             | Est. | Held? |
| ----- | ------------------------------------------------------------------ | ----------------------------------------------------------------------- | ---- | ----- |
| 1     | [`phase-1-member-rows-api.md`](phase-1-member-rows-api.md)         | A row for every in-scope active member, loaded or not                   | 3h   | no    |
| 2     | [`phase-2-empty-state-guard.md`](phase-2-empty-state-guard.md)     | Keep `no_data_in_range` reachable once rows are never empty             | 1h   | no    |
| 3     | [`phase-3-selector-and-blocks.md`](phase-3-selector-and-blocks.md) | `selectUnscheduledTasks` + the `kind: "unscheduled"` block              | 2h   | no    |
| 4     | [`phase-4-render.md`](phase-4-render.md)                           | Chart-side bar, sidebar spacer, overflow-only footer, strings           | 2.5h | no    |
| 5     | [`phase-5-drag.md`](phase-5-drag.md)                               | `anchorDate` on `useTaskBarDrag`, drag + resize wiring, permission gate | 3h   | no    |
| 6     | [`phase-6-verify-docs.md`](phase-6-verify-docs.md)                 | Verify, docs, D8 rewrite, propagation                                   | 2h   | no    |

**Total ~13.5h.** Two independent chains: 1 → 2, and 3 → 4 → 5 → 6. Nothing blocks either now that
PLANE-120 has merged. Phase 6 closes both.

## File ownership

Single-agent cook, sequential within each chain.

| File                                                                                  | Phase |
| ------------------------------------------------------------------------------------- | ----- |
| `apps/api/plane/workload/service.py`                                                  | 1     |
| `apps/api/plane/workload/tests/test_member_rows.py` _(new)_                           | 1     |
| `apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx`                 | 2     |
| `packages/workload-ext/src/merge.ts`                                                  | 3     |
| `packages/workload-ext/src/index.ts` (export)                                         | 3     |
| `apps/web/core/components/workload/timeline/types.ts`                                 | 3     |
| `apps/web/core/components/workload/timeline/blocks.ts`                                | 3     |
| `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`           | 4, 5  |
| `apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx`           | 4     |
| `packages/workload-ext/src/i18n.ts`                                                   | 4, 5  |
| `apps/web/core/components/workload/timeline/useTaskBarDrag.ts`                        | 5     |
| `packages/workload-ext/verify-merge.mjs`                                              | 3, 6  |
| `CLAUDE.md`, `docs/FORK.md`, `plans/260824-workload-timeline-scheduling/plan.md` (D8) | 6     |

**Nothing under `apps/web/core/components/gantt-chart/`, no new Django app, no migration, no
touch-point edit.** `workload/` is already installed; phase 1 adds one function and one union
inside it.

## Risk assessment

| Risk                                                                                   | L   | I   | Score | Mitigation                                                                                                                                                                                                   |
| -------------------------------------------------------------------------------------- | --- | --- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| An empty member row renders as a second "Unassigned" lane                              | 4   | 4   | 16    | `assignee_name` falls back to `"Unassigned"` when `names` has no entry (`service.py:582`), so phase 1 populates `names` from the same query — and asserts on the rendered name, not just the row's existence |
| `no_data_in_range` silently stops firing                                               | 4   | 4   | 16    | D16 / phase 2, whose check is to reproduce the case that would have been lost rather than to read the condition                                                                                              |
| A dashed bar in today's column is still read as "due today"                            | 3   | 4   | 12    | D7 plus the title's explicit "Unscheduled" prefix; phase 4 compares it against a real overdue bar and a real today-dated bar before the phase is done                                                        |
| Filtering to one member still shows everyone's empty lane                              | 4   | 3   | 12    | D15 — the member ids are intersected with `assignee_filter`, with a test for it                                                                                                                              |
| `useTaskBarDrag` cannot position a bar whose two dates are both null                   | 4   | 3   | 12    | Phase 5 adds an explicit `anchorDate` rather than letting `task.start_date ?? task.target_date` resolve to `null`                                                                                            |
| An MCP or SDK consumer reads row count as a work signal                                | 3   | 3   | 9     | Phase 6 propagates the D12 warning to `plane-mcp-server`'s `get_workload` docstring; this repo's own instance of the mistake is phase 2                                                                      |
| Reader adds the footer count to the visible bars                                       | 3   | 3   | 9     | D5 — the footer says `27 more`, never `30`                                                                                                                                                                   |
| Scheduling plan lands with a different `useTaskBarDrag` signature than phase 5 assumes | 3   | 3   | 9     | Phase 5 re-reads the hook as merged before writing a line, treating the plan text as an expectation rather than a fact                                                                                       |
| Membership predicate widens later (bots, inactive members)                             | 2   | 3   | 6     | Phase 1's tests pin the bot and inactive-member exclusions, which no eyeballed response would reveal                                                                                                         |
| Swimlane height grows by 3 rows per member with unscheduled work                       | 3   | 2   | 6     | D4's cap; collapse already defaults to collapsed at Month and Quarter                                                                                                                                        |

## Timeline

| Phase                      | Effort    | Notes                                                                   |
| -------------------------- | --------- | ----------------------------------------------------------------------- |
| Phase 1: member rows (API) | M (~3h)   | Unblocked; Django + pytest                                              |
| Phase 2: empty-state guard | S (~1h)   | Blocked on 1 only                                                       |
| Phase 3: selector + blocks | S (~2h)   | Pure; testable with no browser                                          |
| Phase 4: render            | S (~2.5h) | Blocked on 3                                                            |
| Phase 5: drag              | M (~3h)   | Blocked on 4 only — PLANE-120 merged                                    |
| Phase 6: verify + docs     | S (~2h)   | Closes both chains; rewrites the other plan's D8                        |
| Total                      | ~13.5h    | Critical path is 3 → 4 → 5 → 6; phases 1–2 run beside it or ahead of it |
