# Phase 4 — the write: patch, optimism, rollback

**Owns:** `apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx`,
`packages/workload-ext/src/i18n.ts`
**Estimate:** 2h
**Depends on:** phases 1 and 3

## Goal

Turn phase 3's `onCommit` into a durable change, with the bar staying put on success and snapping
back on failure.

## The handler

Build it in `WorkloadTimelineRoot` and thread it down through `blockToRender` alongside the props
already passed there (`granularity`, `workspaceSlug`). The root is the right home: it already owns
the store instance and the workspace slug, and it is where the existing `noopBlockUpdateHandler`
lives — which this phase should delete, since core's drag stays off and nothing else calls it.
Leave `blockUpdateHandler` itself pointing at a comment explaining that core's path is unused.

```
onCommit(task, dates)
  ├─ snapshot = store.patchTaskDates(task.id, dates)      // optimistic, bar stays put
  ├─ await issueService.patchIssue(slug, task.project_id, task.id, dates)
  ├─ on success  → nothing further; the coverageVersion bump from patchTaskDates
  │                already triggered the viewport refetch
  └─ on failure  → store.rollbackTaskDates(snapshot) + error toast
```

`IssueService` (`services/issue/issue.service.ts:226`) is a plain `APIService` with no store
dependency, so it can be instantiated at module scope in the root — the same pattern
`WorkloadStore` uses for `WorkloadService`. Do **not** reach for `useIssuesActions`: it resolves its
store from `useIssueStoreType()`, and the workload route sits in no issue-layout context.

## Ordering matters

Patch **before** awaiting, not after. The point of D3 is that the bar never leaves the position the
user dropped it in; patching after the response arrives gives a 300–600ms snap-back-then-forward,
which reads as the drag having failed and then silently succeeded.

## Toasts

- **Failure:** `TOAST_TYPE.ERROR`, naming the work item by `task.identifier` and saying the change
  was reverted. The bar moving back is the visual half; the toast is what says why.
- **Success:** none. A toast on every drag is noise, and the bar staying where it was dropped is
  already the confirmation.

Strings go in `packages/workload-ext/src/i18n.ts` (`timeline.reschedule_failed`).

## Concurrency

Two drags in quick succession are safe by construction: each `patchTaskDates` bumps
`coverageVersion`, and `_fetchGap` discards any response whose captured version no longer matches
(`store.ts:315`). No extra guard, no queue.

A rollback that arrives after a **second** drag on the same task would restore stale dates. Guard by
having `rollbackTaskDates` no-op when the task's current dates no longer match what the patch wrote
— the snapshot carries both the before and the after, so this is a comparison, not a timestamp.
Record the check in phase 1's implementation if it is cheaper to put it there; either home is fine,
but it must exist in one of them.

## Success criteria

- `pnpm check` clean.
- Manual: drag a bar, confirm the work item's dates in the peek panel match, reload the page and
  confirm they persist.
- Manual: drag a bar with devtools set to offline; the bar returns to its original position and an
  error toast names the work item.
- Manual: drag two different bars within a second of each other; both land, neither reverts.
- Manual: confirm the heat cells under the moved bar update within a second (the viewport refetch),
  and note that a period scrolled off-screen may not — that is the documented limitation, not a bug
  to chase.
