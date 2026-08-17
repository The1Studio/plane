# Phase 5 — Timeline (Gantt) layout · owns blocker B3

**Goal:** Add the Timeline layout to the Views tab, and resolve the one hard blocker in this
feature: `BaseGanttRoot` requires a route `:projectId` that `/workspace-views/` does not have.

**Effort:** M (~3d) · **Depends on:** Phase 3 · **Parallel with:** Phase 4 (see the shared-append note)
**Resolves:** [`plan.md`](plan.md) § B3 · **Implements:** D5

---

## B3 — the actual blocker

`apps/web/core/components/issues/issue-layouts/gantt/base-gantt-root.tsx:102`, inside
`updateBlockDates`:

```ts
issues.updateIssueDates(workspaceSlug.toString(), updates, projectId.toString());
```

`projectId` comes from `useParams()` (line 51). On `/:workspaceSlug/workspace-views/:globalViewId`
there is no `:projectId` route segment, so it is `undefined` and `.toString()` throws on the first
bar drag.

Two details that narrow the problem:

- **The other Gantt write is already fine.** Line 90 does
  `updateIssue(issue.project_id, issue.id, payload)` — per-issue, no route param. Only
  `updateBlockDates` (the bulk drag path) is broken.
- **`updateIssueDates` is genuinely project-scoped** — a single `projectId` argument for a batch
  of updates. A workspace-wide Timeline can hold items from 12 projects in one drag selection, so
  there is no correct single value to pass. This is a real API-shape mismatch, not a missing cast.

`GanttStoreType` (line 40) also excludes `GLOBAL` — and, unlike List and Board, also excludes
`PROFILE`. No workspace-level Gantt has ever existed upstream.

## D5 — the resolution

**Fall back to per-item `updateIssue` for the global store.** Each `TIssue` carries its own
`project_id`, and line 90 already proves that path works from this component. `updateBlockDates`
becomes: if the store is `GLOBAL`, map the update list through per-item `updateIssue` calls;
otherwise call `updateIssueDates` exactly as today.

Considered and rejected:

- _Group updates by `project_id` and issue one `updateIssueDates` per project_ — fewer requests,
  but adds a fan-out failure mode (partial success across projects with no transaction) for a
  path where a drag typically moves one bar. Revisit only if profiling shows it matters.
- _A new bulk endpoint in `views_ext`_ — real work in Phase 1's app for a rare interaction.
  Defer until per-item is measurably too slow.

Keep the fallback confined behind a store-type check so non-global Gantt is byte-for-byte
unchanged. Do not "unify" the two paths.

## Work

1. **Add `| EIssuesStoreType.GLOBAL` to `GanttStoreType`** (`base-gantt-root.tsx:40`), fenced.
2. **Implement the D5 fallback** in `updateBlockDates`, fenced. Keep it small — this is a core
   file and a permanent rebase surface.
3. **Timeline root in `packages/views-ext`** — template: the `BaseGanttRoot viewId={…}` usage in
   `roots/project-view-layout-root.tsx:37`. Pass the `globalViewId` as `viewId`.
4. **Register the layout** — add `EIssueLayoutTypes.GANTT` to `GLOBAL_VIEW_LAYOUTS`, add the
   `case` to `WorkspaceAdditionalLayouts`, and confirm the fork layout-options table has a
   `gantt_chart` entry (note the key is `gantt_chart`, not `gantt`, in the constants tables —
   check `packages/constants/src/issue/filter.ts` before assuming).
5. **Audit the rest of the component for route-param reads.** `projectId` at line 51 feeds more
   than `updateBlockDates` — quick-add is one known consumer. Read every use before shipping;
   B3 was found by reading, and a second instance would surface as a runtime crash rather than a
   type error.

## Quick-add

`QuickAddIssueRoot` (~line 113) is gated on `enableIssueCreation && isAllowed`. Creating a work
item from a workspace-wide Timeline has no unambiguous target project. Disable quick-add for the
global store rather than defaulting to some project — a silently-wrong project assignment is worse
than a missing button. `WorkspaceIssues.viewFlags` already exposes `enableIssueCreation`; prefer
driving it from there over a new condition.

## Parallel-safety with Phase 4

Both phases append to `GLOBAL_VIEW_LAYOUTS` and to the `WorkspaceAdditionalLayouts` switch. A
shared working tree means the second writer silently overwrites the first
(`rules/parallel-teammate-git-index-race.md`). Separate `git worktree` per lane, or run
sequentially. All other files in the two phases are disjoint.

## Success criteria

- [ ] Timeline button appears and renders bars for items that have start and target dates
- [ ] Items from multiple projects render in one chart
- [ ] **Dragging a bar does not throw** and the new dates persist across reload — this is the B3 regression test
- [ ] Dragging a bar for an item in project A does not write to project B
- [ ] Quick-add is hidden for the global store
- [ ] Items missing start or target dates degrade gracefully (no crash, no zero-width bar)
- [ ] Project / cycle / module / project-view Timelines are unchanged — the D5 branch is global-only
- [ ] Every route-param read in `BaseGanttRoot` audited; any second `projectId` dependency documented here
- [ ] `pnpm check` clean · `plane-isolation-audit` flags no file outside Phase 3's set plus `base-gantt-root.tsx`

## Risks

| Risk                                                            | L   | I   | Score | Mitigation                                                                           |
| --------------------------------------------------------------- | --- | --- | ----- | ------------------------------------------------------------------------------------ |
| A second undiscovered `projectId` dependency crashes at runtime | 3   | 4   | 12    | Step 5 is a full read of every route-param use, not a grep for the one known line    |
| D5 branch regresses project-scoped Timeline                     | 2   | 4   | 8     | Store-type-guarded branch; unchanged-project-Timeline is a success criterion         |
| Per-item updates feel slow on a multi-bar drag                  | 3   | 2   | 6     | Accepted for now; group-by-project is the documented next step if profiling shows it |
| Concurrent append collision with Phase 4                        | 3   | 2   | 6     | Separate worktrees, or run sequentially                                              |

**Deferral is cheap and pre-authorised.** Timeline is last precisely because it is the riskiest.
If step 5 uncovers deeper coupling, ship Phases 1-4 and drop `EIssueLayoutTypes.GANTT` from
`GLOBAL_VIEW_LAYOUTS` — one line, and the other four layouts are unaffected. Record the reason in
`docs/FORK.md` (Phase 6) so the next attempt starts from what was learned.
