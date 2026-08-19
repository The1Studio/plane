# Phase 4 — Clickable work items (peek overlay)

**Goal:** clicking a task bar or its sidebar label opens Plane's work-item peek panel; cmd/ctrl/
middle-click opens the full page. Depends on Phases 1 and 3. Parent: [`plan.md`](plan.md).

## Ownership

- `apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx`
- `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`
- `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx`

## 4.1 — Mount the peek overlay

`<IssuePeekOverview />` is not a global — every layout that supports peek renders it itself
(e.g. `issue-layouts/roots/all-issue-layout-root.tsx:190`). Render it once at the bottom of the
workload page. It self-fetches via `issueOperations.fetch` (`peek-overview/root.tsx:68-75`), so the
issue does **not** need to be preloaded into any issue store — which matters here, because the
workload response is not an issue list.

`useIssueStoreType()` falls back to `EIssuesStoreType.PROJECT` when no route param and no
`IssuesStoreContext` match (`use-issue-layout-store.ts:42`); on the workspace-level workload route
that is the branch we land on, and it is the same branch the profile/workspace layouts rely on. No
provider needed.

## 4.2 — Open on click

Both click targets do the same thing:

```tsx
const { handleRedirection } = useIssuePeekOverviewRedirection();
```

`handleRedirection` (`hooks/use-issue-peek-overview-redirection.tsx:25-52`) wants a `TIssue`, which
we do not have — we have a workload task row. Call the underlying store action directly instead:

```tsx
setPeekIssue({ workspaceSlug, projectId: task.project_id, issueId: task.id });
```

`project_id` is Phase 1.3's addition; without it there is no route to peek to.

Wrap each target in core's `ControlLink` with `href = generateWorkItemLink({ workspaceSlug,
projectId, issueId, projectIdentifier, sequenceId })`, exactly as the issue gantt sidebar does
(`issue-layouts/gantt/blocks.tsx:129-150`) — that is what preserves cmd/ctrl/middle-click to the
full page while a plain click stays in-page. `projectIdentifier` and `sequenceId` are already
derivable from `task.identifier` (`"<PROJECT>-<sequence_id>"`), but prefer
`useProject().getProjectIdentifierById(task.project_id)` over string-splitting the identifier.

On the chart bar, call `e.stopPropagation()` first: the bar sits inside `ChartDraggable`, and
although every drag affordance is disabled (`enableBlockMove` etc. all `false`), the surrounding
`BlockRow` still owns hover/active state.

## 4.3 — Refetch after an edit

The peek panel can change the very fields the workload view aggregates — start date, target date,
assignee, state. Subscribe to peek close (`peekIssue` going `undefined`) and refetch the workload
once, rather than diffing what changed. One request on panel close is cheaper than a stale board.

The estimate itself is edited through `workloadStore.updateEstimate`, which already invalidates its
own caches — no extra wiring.

## Success criteria

- Clicking a bar or a sidebar task label opens the peek panel for that work item.
- Cmd/ctrl/middle-click opens `/:slug/projects/:projectId/issues/:issueId` in a new tab.
- Changing a target date in the panel and closing it updates the bar's position without a reload.
- An "Unassigned" swimlane's tasks are clickable too (they have a `project_id`; only the assignee
  is null).
