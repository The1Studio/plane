# Phase 2 — keep the "no data in range" message reachable

**Owns:** `apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx`
**Estimate:** 1h
**Depends on:** phase 1. **Not blocked by PLANE-120.**

## Goal

Phase 1 makes `rows` non-empty for any workspace that has an active member. One existing condition
reads row count as a proxy for "is there anything here", and it goes quietly dead the moment that
becomes true.

## The condition

```tsx
// WorkloadTimelineRoot.tsx:276
const hasRows = (store.workloadData?.rows.length ?? 0) > 0;
```

`!hasRows` gates an overlay that picks between three messages: loading, `no_data_in_range`
("{count} estimated work items exist, but none fall in this date range — widen it"), and
`no_workload_data`.

After phase 1, `rows.length` is the **member count**, not the work count. So `hasRows` is true on a
board where every single lane is empty, the overlay never renders, and a reader who has scrolled to
a quarter with nothing scheduled sees a wall of blank lanes with nothing telling them why.

The `no_data_in_range` message is the one that hurts to lose. Its own comment records why it was
written: a member with 71 estimated tasks rendered an empty board because every target date fell
just outside the window, and "no rows" and "no data" being conflated is what let that bug hide. This
change re-conflates them from the other direction — the message survives in the code, and becomes
unreachable.

## The fix

Ask whether any row has work, not whether any row exists:

```tsx
// A row per member is not a row per work item. Phase 1 gives every active
// member a lane whether or not they carry anything, so `rows.length` now
// counts PEOPLE and answers nothing about whether this window has work in it.
// Counting the work itself is what keeps `no_data_in_range` reachable — that
// message is the only thing that distinguishes "widen your range" from
// "nothing is estimated at all", and its own history is a bug that hid in
// exactly this ambiguity.
const hasWork = (store.workloadData?.rows ?? []).some(
  (row) => row.tasks.length > 0 || row.total > 0
);
```

Both halves of the predicate are needed, and neither is redundant:

- `tasks.length > 0` catches an **unscheduled-only** member. Their estimate is routed to the
  separate `unscheduled` bucket, never to `buckets`, so their `total` is `0` while they plainly
  have work — the very population phases 3–5 exist to draw.
- `total > 0` catches a member whose work is **truncated past the 200-task cap** or otherwise
  contributes hours without a task row surviving into `tasks`.

Rename `hasRows` to `hasWork` rather than redefining it in place. The name is the thing that misled;
leaving it while changing its meaning sets the same trap for the next reader.

## Check it by breaking it

The overlay's whole failure mode is silence, so confirm it fires rather than assuming:

1. Pan to a date range with no scheduled work, on a workspace that **does** have estimates
   elsewhere. Expect `no_data_in_range` over a board of empty lanes — this is the case that was
   about to be lost.
2. A workspace with members but zero estimates anywhere. Expect `no_workload_data`.
3. A range with work in it. Expect no overlay at all.

If (1) shows lanes and no message, `hasWork` is still reading row count somewhere.

## Done when

`pnpm --filter web typecheck` passes and all three cases above render the message they should. This
phase writes no new component and adds no string.
