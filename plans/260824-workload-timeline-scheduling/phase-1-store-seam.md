# Phase 1 — a per-task date-mutation seam on the workload store

**Owns:** `packages/workload-ext/src/store.ts`, `packages/workload-ext/verify-merge.mjs`
**Estimate:** 2h
**Depends on:** nothing

## Goal

Give the timeline a way to change a task's dates in the client cache and have the board correct
itself, without blanking. Today the only invalidation is `resetCoverage()` (`store.ts:248`), which
sets `workloadData = null` — fine once when the peek panel closes, unacceptable after every drag.

## What to add

Two actions on `WorkloadStore` (and the matching entries on `IWorkloadStore` and the
`makeObservable` map — all three must be updated together or MobX will not track them):

```ts
patchTaskDates(issueId: string, dates: { start_date: string | null; target_date: string }): TTaskDatesSnapshot
rollbackTaskDates(snapshot: TTaskDatesSnapshot): void
```

`TTaskDatesSnapshot` is a new exported type in `types.ts`: the issue id plus the dates as they were
before the patch, so phase 4 can restore them on a rejected write.

### `patchTaskDates` — four steps, in this order

1. **Patch every occurrence.** Iterate `workloadData.rows` and, for each row, replace any task whose
   `id === issueId`. A work item with two assignees appears on **two rows** (`TWorkloadTask.hours`
   is that assignee's share) — patching only the first would leave the same bar in two places
   showing two different date ranges. Capture the pre-patch dates from the first occurrence found;
   that is the snapshot's payload.
2. **Recompute `overdue` on the patched task.** It is `target_date < today` and `state_group` is
   neither `completed` nor `cancelled`. Getting this wrong leaves a bar red after it has been
   dragged into the future, which reads as a bug in the drag rather than in the flag.
3. **Replace `workloadData` with a new object** (new `rows` array, new row objects for the rows
   that changed). The timeline's `blockIds` memo keys on `store.workloadData`
   (`WorkloadTimelineRoot.tsx`), so a mutation in place would not re-run `packTasksIntoLanes` and
   the bar would not repack.
4. **Invalidate without blanking:** `this.loadedRanges = []` and `this.coverageVersion += 1`.
   Deliberately **not** `resetCoverage()` — see D11.

Step 4 does three jobs at once, all through machinery that already exists:

- Clearing `loadedRanges` makes the next `ensureRange` treat the whole viewport as a gap, so it
  refetches instead of short-circuiting on `gaps.length === 0` (`store.ts:266`).
- Bumping `coverageVersion` makes `_fetchGap` discard any response that was already in flight when
  the patch landed (`store.ts:315` compares `requestedVersion`), which is what stops a stale
  response from overwriting the freshly patched dates.
- The same bump fires the timeline's existing `coverageVersion` effect, which calls `syncViewport`
  and therefore `ensureRange`. Nothing new has to be wired on the React side.

**Do not** recompute `buckets`, `month_buckets`, `over`, `total`, or `capacity_buckets`. Doing so
means reimplementing `apps/api/plane/workload/aggregation.py` in TypeScript; the refetch supplies
them, and `mergeRow`'s `{...base, ...add}` (`merge.ts`) lets the fresh values win on every period
key the viewport covers. Write a comment saying so, with the reason, so the next reader does not
"fix" the omission.

### `rollbackTaskDates`

Applies the snapshot back through the same code path as step 1–3, and bumps `coverageVersion`
again. It does **not** need to clear `loadedRanges` a second time — the patch already did, and the
refetch it triggered will carry the server's truth either way.

## Success criteria

- `pnpm --filter @plane/workload-ext check:types` is clean.
- A new block of assertions in `verify-merge.mjs` covers, at minimum:
  - patching a task that appears on **two** rows updates both;
  - `workloadData` is a **different object** after a patch (identity changed);
  - `overdue` flips to `false` when a past-due task is moved into the future, and to `true` when a
    future task is moved into the past;
  - `rollbackTaskDates` restores the exact pre-patch dates on every occurrence;
  - `buckets` are **untouched** by a patch — this one asserts the deliberate omission, so a future
    "improvement" that starts recomputing them fails loudly instead of silently diverging from the
    server.
- `pnpm --filter @plane/workload-ext build && node verify-merge.mjs` prints no `FAIL`.

## Out of scope

No React, no network, no permission logic. This phase is pure store surface.
