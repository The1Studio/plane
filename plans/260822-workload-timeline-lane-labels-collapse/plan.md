# Workload timeline — drop lane sidebar labels, default-collapse at Month/Quarter

**Repo:** `The1Studio/plane` (`company-main`)
**Scope:** frontend only, fork-owned files under `apps/web/core/components/workload/timeline/`
**Effort:** ~2h total (S)

## Goal

Two changes to the workspace workload timeline, both driven from the annotated
screenshot `swappy-20260822_174914.png`:

1. **Remove the lane labels from the left sidebar.** The circled cells —
   `12 items`, `4 items`, `CODEBASE-131`, `CODEBASE-132` — are the sidebar
   cells of `kind: "lane"` blocks. They go away entirely. The `Unscheduled (26)`
   strip directly below them is a `kind: "footer"` block and **stays**.
2. **Default-collapse every swimlane in Month and Quarter zoom.** Week zoom keeps
   its current expanded default.

## Prior art — what already exists (searched: `apps/web/core/components/workload/`, `packages/workload-ext/`)

| Thing | Where | Note |
|---|---|---|
| Lane sidebar cell rendering `N items` / identifier | `timeline/WorkloadTimelineSidebarRow.tsx` (`data.kind === "lane"` branch) | The exact cells circled in the screenshot |
| Footer strip (`Unscheduled (N)` / `Overdue (N)`) | same file, `data.kind === "footer"` branch | Must be left untouched |
| Collapse state | `timeline/WorkloadTimelineRoot.tsx` — `useState<ReadonlySet<string>>` + `toggleCollapse` | Membership set; no notion of a per-view default |
| Collapse consumption | `timeline/blocks.ts` — `buildWorkloadBlocks(data, granularity, collapsedAssigneeKeys)` | Skips lane + footer blocks for a collapsed key, keeps the header |
| Zoom → granularity map | `WorkloadTimelineRoot.tsx` — `VIEW_TO_GRANULARITY` (`week→day`, `month→week`, `quarter→month`) | The zoom (`timelineStore.currentView`) is the only time control; it is a MobX observable and the root is already an `observer` |
| `assigneeKey()` / `UNASSIGNED_KEY` | `timeline/types.ts` | Stable key per swimlane, `null → "unassigned"` |

Zero test files reference `buildWorkloadBlocks`, `WorkloadTimelineSidebarRow`, or
`packTasksIntoLanes` — searched across `apps/` and `packages/` (excluding
`node_modules`). No test updates are implied by either change.

## Resolved decisions

| # | Decision |
|---|---|
| D1 | The lane sidebar cell renders as an **empty** `SidebarCell`, not as a removed row. The cell must keep occupying `BLOCK_HEIGHT` (44px) or the sidebar column desynchronises from the chart body, which stacks one `BlockRow` per `blockId`. |
| D2 | Both the aggregate label (`N items`) and the single-task identifier (`CODEBASE-131`) go. The screenshot circles both; there is no surviving lane label of any shape. |
| D3 | Switching zoom **resets** manual collapse/expand toggles to the new view's default. Arriving at Month/Quarter always collapses everything; arriving at Week always expands everything. Refined by D7 for the Month↔Quarter case, where the default does not change. |
| D4 | The `Unassigned` swimlane collapses by default exactly like a member row. Month/Quarter is a uniform one-line-per-row capacity board. |
| D5 | The default is derived from `timelineStore.currentView` (the gantt zoom), not from `store.granularity`. They are equivalent today via `VIEW_TO_GRANULARITY`, but the user's requirement is phrased in zoom terms and `currentView` is the value the header control actually sets. |
| D6 | Late-arriving rows must honour the default. The collapse model therefore becomes *default + per-key override*, evaluated per key at render, rather than a materialised set built once from the rows present at the time of the view change. Rows load asynchronously from viewport-driven `ensureRange` calls, so a set snapshotted at view-change time would leave every subsequently-loaded row expanded in Month view. |
| D7 | The zoom-change reset fires only when the *default* flips — i.e. on Week↔Month and Week↔Quarter, not on Month↔Quarter. Month and Quarter share a default, so switching between them keeps today's behaviour of leaving manual toggles alone. Implemented by keying the reset effect on `defaultCollapsed`, not on `currentView`. |

## Phases

| Phase | File | Effort | Depends on |
|---|---|---|---|
| 1 | `phase-1.md` — remove lane sidebar labels | S (~0.5h) | — |
| 2 | `phase-2.md` — view-driven default collapse | S (~1.5h) | Phase 1 (both edit `WorkloadTimelineSidebarRow.tsx`) |

Sequential, single-agent. The two phases share a file, so they are **not**
parallel-safe and no fan-out roster is emitted.

## Fork discipline

Both phases touch only files already owned by this fork
(`apps/web/core/components/workload/timeline/`, created by the workload
timeline work and documented in `docs/FORK.md` § "Workload timeline"). **No new
core-edit exception is introduced**, no touch-point file is modified, and
`docs/FORK.md`'s core-edit exception table needs no new row — these are
behavioural tweaks inside fork-owned components, not new seams into core.

## Downstream propagation

**None required.** Neither change adds or alters an endpoint, a response field,
or an API behaviour — both are presentation-only, inside `apps/web`. The
`get_workload` MCP tool, the SDKs, and the docs describe the API surface, which
is unchanged. No sibling-repo issue or PR is opened for this work.

`CLAUDE.md` § "Custom features (fork-owned)" gets one clause appended to the
`workload/` bullet recording the Month/Quarter default-collapse behaviour, since
that bullet already documents the timeline's interaction model.

## Risk Assessment

| Risk | Likelihood (1-5) | Impact (1-5) | Score | Mitigation |
|---|---|---|---|---|
| Removing the lane label collapses the sidebar cell's height, desynchronising sidebar rows from chart rows | 2 | 5 | 10 | D1 — keep the `SidebarCell` wrapper with its explicit `height: BLOCK_HEIGHT` style; only the children go. Verify visually that a member's bars still line up with their sidebar row. |
| Rows loaded after a zoom change render expanded in Month/Quarter | 3 | 3 | 9 | D6 — evaluate the default per key at render instead of materialising a set at view-change time. |
| Blank sidebar cells make an expanded member's rows unreadable in Week zoom | 2 | 2 | 4 | Accepted and explicitly requested. Each bar already carries its own name, hours, and a `title` with the identifier; the sidebar label was duplicative. |
| Stale comments left behind describing the removed label | 4 | 1 | 4 | Phase 1 explicitly lists the two comment sites to update (`WorkloadTimelineSidebarRow.tsx` header block, `WorkloadTimelineChartBlock.tsx` ~line 126). |

No risk scores ≥ 15.

## Timeline

| Phase | Effort | Notes |
|---|---|---|
| Phase 1: remove lane sidebar labels | S (~0.5h) | Self-contained |
| Phase 2: view-driven default collapse | S (~1.5h) | Critical path; touches 3 files |
| Total | ~2h | Critical path: Phase 1 → Phase 2 |
