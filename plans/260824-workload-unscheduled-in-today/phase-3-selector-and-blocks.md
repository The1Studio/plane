# Phase 3 — the unscheduled selector and its block kind

**Owns:** `packages/workload-ext/src/merge.ts`, `packages/workload-ext/src/index.ts`,
`apps/web/core/components/workload/timeline/types.ts`,
`apps/web/core/components/workload/timeline/blocks.ts`,
`packages/workload-ext/verify-merge.mjs`
**Estimate:** 2h
**Depends on:** nothing in code. Ships after phases 1–2 for branch order only.

## Goal

Turn the unscheduled tasks already sitting in `row.tasks` into ordered blocks the chart can lay out,
without touching `packTasksIntoLanes` and without changing what a scheduled bar does.

## The pure selector

Add to `packages/workload-ext/src/merge.ts`, beside `packTasksIntoLanes` — same file because it is the
same concern (turning a row's tasks into rows of the chart), and because `verify-merge.mjs` already
imports from there.

```ts
/**
 * How many unscheduled bars a swimlane draws before the footer takes over.
 * Each costs a full 44px chart row per member, so this is a height budget, not
 * a display preference: a member with 30 unscheduled items would otherwise be
 * 30 rows tall and push every other member off the screen.
 */
export const MAX_UNSCHEDULED_LANES = 3;

export type TUnscheduledSelection = {
  /** At most `MAX_UNSCHEDULED_LANES`, in server order. */
  shown: TWorkloadTask[];
  /** How many unscheduled tasks the cap left out. 0 when everything fits. */
  hiddenCount: number;
};

export function selectUnscheduledTasks(
  tasks: TWorkloadTask[],
  maxLanes: number = MAX_UNSCHEDULED_LANES
): TUnscheduledSelection;
```

Rules, in order:

1. **`unscheduled` means `!task.target_date`** — the same predicate `packTasksIntoLanes` filters *out*
   and the footer already counts. The two must stay complements: any task the packer drops is a task
   this selector must see, or work disappears from the board entirely.
2. **Preserve server order; do not sort.** `service.py`'s `_task_sort_key` already ordered `tasks` by
   `(start is None, start, target is None, target)`, so within the unscheduled group a task with a
   start sorts ahead of one with nothing. Re-sorting here would fight that and make the three shown
   bars jump between refetches. `filter` returns a new array, so nothing in the store's response object
   is mutated — the same reason `packTasksIntoLanes` filters before sorting.
3. `hiddenCount = max(0, total - shown.length)`.
4. `maxLanes <= 0` yields `shown: []` and `hiddenCount: total` — the caller gets a valid selection, not
   an exception.

Export both the constant and the function from `packages/workload-ext/src/index.ts`.

## The anchor

Also in `merge.ts`, because it is arithmetic and phase 4 and phase 5 both need exactly this rule:

```ts
/**
 * The date column an unscheduled bar is drawn in (D3).
 *
 * A task with a `start_date` but no `target_date` is unscheduled by this
 * codebase's definition — both `packTasksIntoLanes` and the footer key on
 * `target_date` alone — but it already carries a date somebody chose. Drawing
 * it anywhere else would overwrite that choice visually. Only the fully
 * dateless case falls back to today.
 */
export function unscheduledAnchorDate(task: TWorkloadTask, todayISO: string): string {
  return task.start_date ?? todayISO;
}
```

`todayISO` is passed in rather than read from `new Date()` inside, so `verify-merge.mjs` can assert
against a fixed day and the function stays pure.

## The block kind

In `apps/web/core/components/workload/timeline/types.ts`, add a fourth member to
`TWorkloadTimelineBlockData`:

```ts
/**
 * ONE unscheduled task, drawn as a placeholder bar at its anchor column.
 *
 * Its own kind rather than a `kind: "lane"` with a single task, because a
 * lane's box is min(start)..max(target) of its tasks — for a dateless task
 * that box is one column wide, and a bar held at MIN_BAR_WIDTH would overflow
 * it. This block instead spans the WHOLE window, exactly as the header and
 * footer do, and positions its bar inside that box against the block's own
 * marginLeft. That is the header's heat-cell technique, reused.
 */
export type TWorkloadUnscheduledBlockData = {
  kind: "unscheduled";
  id: string;
  name: string;
  assigneeId: string | null;
  task: TWorkloadTask;
  /** `start_date ?? today` — resolved once in blocks.ts so every consumer agrees. */
  anchorDate: string;
  sort_order: number;
  start_date: string;
  target_date: string;
};
```

Also add `unscheduledHidden: number` to `TWorkloadFooterBlockData`. The footer cannot recompute it: it
holds the whole `row`, and the number it needs is a function of the cap the builder applied. Passing it
down is what keeps phase 4's footer honest without duplicating the cap in two places.

## Wiring it into `buildWorkloadBlocks`

`blocks.ts` gains a `todayISO: string` parameter (fifth, after `isCollapsed`). Passed in, not read from
`new Date()`, for the same reason as above — and because a builder that reads the clock cannot be
tested.

Emission order inside the expanded branch of each row, **before** the scheduled lanes:

```
wl-header:<key>
wl-unsched:<key>:0        ← selection.shown[0]
wl-unsched:<key>:1
wl-unsched:<key>:2
wl-lane:<key>:0           ← unchanged
wl-lane:<key>:1
wl-footer:<key>
```

- The selector runs once per row; hold its result for both the unscheduled blocks and the footer's
  `unscheduledHidden`.
- Unscheduled blocks are skipped entirely when `isCollapsed(key)` — same guard as the lanes, same
  `continue`. A collapsed member is one line.
- `start_date`/`target_date` on each unscheduled block are `headerStart`/`headerEnd`, byte-identical to
  what the header and footer already use. Do not compute a narrower span.
- `sort_order` continues off the same `order++` counter, so nothing else shifts.

## The footer's emission condition changes

Today: `row.tasks.some((t) => !t.target_date) || row.tasks.some((t) => t.overdue) || row.tasks_truncated`.

It becomes `selection.hiddenCount > 0 || row.tasks.some((t) => t.overdue) || row.tasks_truncated`.

This is the load-bearing half of D5. Without it, a member with two unscheduled tasks gets two visible
bars *and* a footer strip saying `Unscheduled (2)` about the same two bars.

## Verification

Extend `packages/workload-ext/verify-merge.mjs` with `selectUnscheduledTasks` cases. Assert, at minimum:

| Case | Expectation |
| --- | --- |
| 5 unscheduled, cap 3 | `shown.length === 3`, `hiddenCount === 2`, and `shown` is the first three of the input in input order |
| 2 unscheduled, cap 3 | `hiddenCount === 0` |
| 0 unscheduled | `shown` empty, `hiddenCount === 0` |
| Mixed scheduled + unscheduled | no task with a `target_date` appears in `shown` |
| Input array | not mutated — compare a pre-captured copy after the call |
| `unscheduledAnchorDate` with a start | returns the start, **not** today |
| `unscheduledAnchorDate` with neither date | returns the `todayISO` passed in |

These are pure-function assertions; no browser, no MobX.

## Done when

`node packages/workload-ext/verify-merge.mjs` passes with the new cases, and `buildWorkloadBlocks`
returns `wl-unsched:*` ids in the order above for a fixture row carrying both kinds of task. Nothing
renders yet — that is phase 4.
