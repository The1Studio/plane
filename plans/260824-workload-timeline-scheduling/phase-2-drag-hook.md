# Phase 2 — `useTaskBarDrag`, the pointer/date math

**Owns:** `apps/web/core/components/workload/timeline/useTaskBarDrag.ts` _(new file)_
**Estimate:** 3.5h
**Depends on:** phase 1 (for the commit callback's type only — the hook does not call the store)

## Goal

One hook that turns pointer events on a bar into a `{ start_date, target_date }` pair, and reports
the in-progress pixel offset so the bar can follow the cursor. It owns no store access, no network,
and no permission logic — those belong to phases 3 and 4. Keeping it that way is what makes its
arithmetic testable without a browser.

## Why not core's `useGanttResizable`

It reads and writes `block.position` and calls `updateBlockPosition` on the timeline store
(`gantt-chart/helpers/blockResizables/use-gantt-resizable.ts:110`). A workload bar has no block of
its own — its lane does. Driving it through that hook would move every bar in the lane. See the
plan's "The finding that shapes the whole design".

## Shape

```ts
type TDragMode = "move" | "resize-start" | "resize-end";

useTaskBarDrag({
  task,                    // TWorkloadTask
  chart,                   // ChartDataType — currentViewData
  laneMarginLeft,          // px, the lane block's own origin
  disabled,                // permission gate, from phase 3
  onCommit,                // (dates: { start_date: string | null; target_date: string }) => void
}) => {
  onPointerDown: (e: React.PointerEvent, mode: TDragMode) => void;
  preview: { left: number; width: number } | null;   // null when not dragging
  isDragging: boolean;
  suppressClick: boolean;   // true from the moment the threshold is crossed until the next click
}
```

## Behaviour, point by point

**Threshold (D6).** `pointerdown` records the origin and captures the pointer, but sets nothing.
Only once `|clientX - originX| >= 4` does `isDragging` become true. Below that the pointer-up is a
plain click and `WorkloadTaskLink` opens the peek panel exactly as it does today. This is the whole
reason the bar can stay a `ControlLink`.

**Pointer capture, not document listeners.** Use `setPointerCapture` on the handle element so the
drag survives the cursor leaving the bar, and so a lost pointer (alt-tab, touch cancel) fires
`pointercancel` and aborts cleanly. Core's hook attaches `document`-level `mousemove`/`mouseup`
listeners; capture is the better-scoped equivalent and removes the manual teardown.

**Snapping.** Every frame, the raw pixel delta is snapped:
`snapped = Math.round(rawDelta / chart.data.dayWidth) * chart.data.dayWidth`. Report the snapped
value in `preview`, not the raw one — a bar that slides continuously and then jumps on drop lies
about where it will land.

**Date conversion, on drop only (D9).** Convert from **absolute** chart pixels, never lane-relative:
`getDateFromPositionOnGantt(absPx, chart)` measures from `chart.data.startDate`
(`gantt-chart/views/helpers.ts:73`). The bar's absolute origin is
`getPositionFromDate(chart, task.start_date ?? task.target_date, 0)`; add the snapped delta to that
before converting. Subtracting `laneMarginLeft` is a rendering concern only and must not reach this
conversion.

**Mode semantics.**

| Mode           | Writes        | Rule                                                                                                                                       |
| -------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `move`         | both dates    | Shift both by the same day count, preserving duration (D7). A task with a null `start_date` gains one equal to its new `target_date` (D8). |
| `resize-start` | `start_date`  | Clamped to at most `target_date` minus one day. A null `start_date` is materialised at the dragged position.                               |
| `resize-end`   | `target_date` | Clamped to at least `start_date` plus one day, when a start exists.                                                                        |

**The clamp is a stop, not a rejection.** Dragging the left edge past the right edge parks it one
day short and stays there; it does not cancel the drag or swap the dates. A swap would silently
rewrite the user's intent.

**Escape aborts.** A `keydown` of `Escape` while dragging clears `preview` and skips `onCommit`, so
a drag begun by accident costs nothing.

**No commit when nothing moved.** If the snapped delta is zero on drop, return without calling
`onCommit` — a network round-trip and a cache invalidation for a no-op is pure cost.

## Extract the arithmetic

Put the pure parts in exported functions in the same file so phase 6 can assert them from node
without a DOM:

```ts
export function shiftDates(task, days): { start_date: string | null; target_date: string };
export function resizeStart(task, newStart): { start_date: string; target_date: string };
export function resizeEnd(task, newEnd): { start_date: string | null; target_date: string };
```

The hook becomes a thin pointer wrapper over these three.

## Success criteria

- `pnpm check` clean.
- The three exported functions handle: a null `start_date`, a single-day task, a clamp collision in
  both directions, and a zero-day shift.
- Nothing in this file imports from `@/hooks/store/*`, `@plane/workload-ext`'s store, or any
  service. If it does, the boundary has slipped and phases 3–4 will be untestable.
