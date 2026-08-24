// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-2-drag-hook.md) — pointer/date math for
// dragging or resizing a single task bar. Pure pointer → date conversion only: no
// store access, no network call, and no permission logic (those belong to phases
// 3 and 4, WorkloadTimelineChartBlock/WorkloadTimelineRoot).
//
// `shiftDates`/`resizeStart`/`resizeEnd` — the pure date algebra this hook's pixel
// math ultimately calls into — live in `@plane/workload-ext`'s `dateRange.ts`, not
// here (phase-6-verify-docs.md "Pure-function assertions"): that package's
// `verify-merge.mjs` is a hand-runnable node script with no DOM, and this file
// cannot be imported from it since it lives in apps/web.
//
// See plans/260824-workload-timeline-scheduling/phase-2-drag-hook.md (D5-D10) for
// the full behavioural spec this file implements.

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChartDataType } from "@plane/types";
import { renderFormattedPayloadDate } from "@plane/utils";
import { daysBetween, resizeEnd, resizeStart, shiftDates } from "@plane/workload-ext";
import type { TDatedTask, TDraggedDates, TWorkloadTask } from "@plane/workload-ext";
import { getDateFromPositionOnGantt, getPositionFromDate } from "@/components/gantt-chart/views";

export type { TDraggedDates } from "@plane/workload-ext";

export type TDragMode = "move" | "resize-start" | "resize-end";

/** D6 — pixels of real pointer movement before a pointerdown becomes a drag rather
 *  than a click. Below this, pointer-up is a plain click and falls through to the
 *  bar's `ControlLink` unchanged. */
const DRAG_THRESHOLD_PX = 4;

/**
 * Converts a drag position back to a `YYYY-MM-DD` string. `anchorDate`'s own
 * absolute pixel position (offset 0 — a rendering-relevant offset, like the
 * end-of-day `+dayWidth` used for a bar's right edge, is a rendering concern and
 * must not reach this conversion) plus the already-snapped pixel delta is the
 * position `getDateFromPositionOnGantt` resolves back to a date.
 */
function pixelToDateString(chart: ChartDataType, anchorDate: string, snappedDeltaPx: number): string {
  const anchorPos = getPositionFromDate(chart, anchorDate, 0);
  const date = getDateFromPositionOnGantt(anchorPos + snappedDeltaPx, chart);
  const dateStr = renderFormattedPayloadDate(date);
  // Both helpers are fed a real Date/valid chart the whole way through here, so this
  // is an invariant, not a real failure mode — surfacing it loudly beats a silent NaN.
  if (!dateStr) throw new Error("useTaskBarDrag: failed to convert a drag position back to a date");
  return dateStr;
}

function computeDraggedDates(
  mode: TDragMode,
  task: TDatedTask,
  chart: ChartDataType,
  snappedDeltaPx: number
): TDraggedDates {
  if (!task.target_date) throw new Error("useTaskBarDrag: task has no target_date and cannot be dragged");

  switch (mode) {
    case "move": {
      // Anchor is the bar's own drawn origin (WorkloadTimelineChartBlock uses the
      // same `start_date ?? target_date` rule to position it) — never lane-relative.
      const anchor = task.start_date ?? task.target_date;
      const newAnchor = pixelToDateString(chart, anchor, snappedDeltaPx);
      return shiftDates(task, daysBetween(anchor, newAnchor));
    }
    case "resize-start": {
      const anchor = task.start_date ?? task.target_date;
      const newStart = pixelToDateString(chart, anchor, snappedDeltaPx);
      return resizeStart(task, newStart);
    }
    case "resize-end": {
      const newEnd = pixelToDateString(chart, task.target_date, snappedDeltaPx);
      return resizeEnd(task, newEnd);
    }
  }
}

/**
 * The lane-relative `{ left, width }` a bar at `dates` would occupy — the SAME math
 * WorkloadTimelineChartBlock uses to place a static bar (`start_date ?? target_date`
 * for the left edge, `target_date` landed on the END of its day for the right one),
 * so the preview always matches exactly where a commit would land it. Deliberately
 * does not apply the block's `MIN_BAR_WIDTH` legibility floor — that is a rendering
 * concern for phase 3 to apply the same way it already does for the static case.
 */
function previewFromDates(
  dates: TDraggedDates,
  chart: ChartDataType,
  laneMarginLeft: number
): { left: number; width: number } {
  const start = dates.start_date ?? dates.target_date;
  const startPos = getPositionFromDate(chart, start, 0);
  const endPos = getPositionFromDate(chart, dates.target_date, chart.data.dayWidth);
  return { left: startPos - laneMarginLeft, width: endPos - startPos };
}

// ── The hook ───────────────────────────────────────────────────────────────────

type TUseTaskBarDragParams = {
  task: TWorkloadTask;
  chart: ChartDataType;
  /** The lane block's own pixel origin — see WorkloadTimelineChartBlock's `laneMarginLeft`. */
  laneMarginLeft: number;
  /** Permission gate from phase 3 — when true, `onPointerDown` is a no-op. */
  disabled: boolean;
  onCommit: (dates: TDraggedDates) => void;
};

type TUseTaskBarDragResult = {
  onPointerDown: (e: React.PointerEvent<HTMLElement>, mode: TDragMode) => void;
  preview: { left: number; width: number } | null;
  isDragging: boolean;
  /** True from the moment the 4px threshold is crossed until the click the browser
   *  synthesizes for that pointerdown/up pair has been swallowed (see `finishDrag`
   *  below) — the signal phase 3 uses to keep a real drag from also navigating. */
  suppressClick: boolean;
};

type TDragState = {
  mode: TDragMode;
  pointerId: number;
  element: HTMLElement;
  originClientX: number;
  originTask: TDraggedDates;
  crossedThreshold: boolean;
  /** The snapped pixel delta as of the most recent pointermove — the "did anything
   *  actually move" signal `finishDrag` gates a commit on (not a date comparison,
   *  since resize-start/move can legitimately materialize a null date at zero
   *  net movement; see `shiftDates`/`resizeStart`'s own doc comments). */
  lastSnappedDeltaPx: number;
  pendingDates: TDraggedDates | null;
  handlePointerMove: (ev: PointerEvent) => void;
  handlePointerUp: (ev: PointerEvent) => void;
  handlePointerCancel: (ev: PointerEvent) => void;
  handleKeyDown: (ev: KeyboardEvent) => void;
};

export function useTaskBarDrag({
  task,
  chart,
  laneMarginLeft,
  disabled,
  onCommit,
}: TUseTaskBarDragParams): TUseTaskBarDragResult {
  const [preview, setPreview] = useState<{ left: number; width: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [suppressClick, setSuppressClick] = useState(false);
  const dragStateRef = useRef<TDragState | null>(null);

  const cleanup = useCallback(() => {
    const state = dragStateRef.current;
    if (!state) return;
    state.element.removeEventListener("pointermove", state.handlePointerMove);
    state.element.removeEventListener("pointerup", state.handlePointerUp);
    state.element.removeEventListener("pointercancel", state.handlePointerCancel);
    window.removeEventListener("keydown", state.handleKeyDown);
    dragStateRef.current = null;
  }, []);

  // Unmount safety — a component torn down mid-drag (e.g. a filter change) must not
  // leave listeners attached to a detached element.
  useEffect(() => cleanup, [cleanup]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>, mode: TDragMode) => {
      if (disabled) return;
      if (e.button !== 0) return;
      // A task with no target_date is never drawn (D8) and so should never reach
      // here, but refusing explicitly beats crashing inside pixelToDateString.
      if (!task.target_date) return;
      if (dragStateRef.current) return; // a drag is already in progress

      const element = e.currentTarget;
      const originClientX = e.clientX;
      const originTask: TDraggedDates = { start_date: task.start_date, target_date: task.target_date };

      const handlePointerMove = (ev: PointerEvent) => {
        const state = dragStateRef.current;
        if (!state || ev.pointerId !== state.pointerId) return;
        const rawDelta = ev.clientX - state.originClientX;

        if (!state.crossedThreshold) {
          if (Math.abs(rawDelta) < DRAG_THRESHOLD_PX) return;
          state.crossedThreshold = true;
          setIsDragging(true);
          setSuppressClick(true);
        }

        // Snapped BEFORE conversion, and reported in `preview` rather than the raw
        // delta — a bar that slides continuously and then jumps on drop lies about
        // where it will land (D5).
        const dayWidth = chart.data.dayWidth;
        const snappedDeltaPx = Math.round(rawDelta / dayWidth) * dayWidth;
        state.lastSnappedDeltaPx = snappedDeltaPx;

        const dates = computeDraggedDates(state.mode, state.originTask, chart, snappedDeltaPx);
        state.pendingDates = dates;
        setPreview(previewFromDates(dates, chart, laneMarginLeft));
      };

      /** Tears down the drag. `swallowNextClick` governs whether the click the
       *  browser is about to synthesize for this pointerdown/up pair gets caught.
       *
       *  BOTH a genuine pointerup AND an Escape-abort need to swallow the next
       *  click: the pointer button is still down when Escape fires, and the
       *  eventual `pointerup` synthesizes a `click` on the bar regardless of how
       *  the drag ended. If the abort path does not arm the swallow, that trailing
       *  click reaches `WorkloadTaskLink` with `suppressClick === false` and opens
       *  the peek panel — exactly the outcome D6 exists to prevent (I2).
       *
       *  Only `pointercancel` truly produces no synthesised click (the browser
       *  cancels the gesture outright), so it is the one path that resets
       *  `suppressClick` immediately. */
      const finishDrag = (commit: boolean, swallowNextClick: boolean) => {
        const state = dragStateRef.current;
        cleanup();
        setPreview(null);
        setIsDragging(false);

        if (!state?.crossedThreshold) return;

        if (commit && state.lastSnappedDeltaPx !== 0 && state.pendingDates) {
          onCommit(state.pendingDates);
        }

        if (!swallowNextClick) {
          setSuppressClick(false);
          return;
        }

        // A capture-phase listener directly on the bar's own DOM node fires before
        // the click ever reaches the node's own React (root-delegated) onClick
        // handler — bubbling to the delegation root is strictly later than the
        // "at target" stage, so this is enough to keep the drag from also opening
        // the peek panel.
        //
        // `{ once: true }` self-removes IF the click fires, but it is NOT inert
        // when no click arrives: the listener stays armed and `suppressClick`
        // stays `true` in React state, so the NEXT unrelated click on that bar
        // is silently swallowed and double-blocked (I3). Two guards close that
        // leak: (a) a `pointerdown` on the same element disarms both the
        // listener and `suppressClick` immediately — a real click is always
        // preceded by a pointerdown on the same target; (b) a `setTimeout(0)`
        // fallback clears them on the next task tick, so even a click that
        // arrives with no prior pointerdown (programmatic, assistive tech) is
        // not eaten. The `setTimeout(0)` fallback is also what covers an
        // unmount inside this window: the timer still fires on the detached
        // element and removes both listeners (the state setter is then a
        // harmless no-op), so nothing is stranded. `cleanup` does NOT know
        // about these listeners — they are born after it ran and disarm
        // themselves through the three paths above.
        const disarmSwallow = () => {
          element.removeEventListener("click", swallowClick, { capture: true });
          element.removeEventListener("pointerdown", disarmSwallow);
          clearTimeout(disarmTimer);
          setSuppressClick(false);
        };
        const swallowClick = (ev: MouseEvent) => {
          ev.stopPropagation();
          ev.preventDefault();
          disarmSwallow();
        };
        const disarmTimer = window.setTimeout(disarmSwallow, 0);
        element.addEventListener("click", swallowClick, { capture: true });
        element.addEventListener("pointerdown", disarmSwallow);
      };

      const handlePointerUp = (ev: PointerEvent) => {
        const state = dragStateRef.current;
        if (!state || ev.pointerId !== state.pointerId) return;
        finishDrag(true, true);
      };

      const handlePointerCancel = (ev: PointerEvent) => {
        const state = dragStateRef.current;
        if (!state || ev.pointerId !== state.pointerId) return;
        finishDrag(false, false);
      };

      // Escape aborts: clears preview and skips onCommit. The pointer button is
      // still down, so the trailing `pointerup` will still synthesise a `click` —
      // arm the swallow (I2) so that click does not open the peek panel.
      const handleKeyDown = (ev: KeyboardEvent) => {
        if (ev.key !== "Escape") return;
        finishDrag(false, true);
      };

      element.setPointerCapture(e.pointerId);
      element.addEventListener("pointermove", handlePointerMove);
      element.addEventListener("pointerup", handlePointerUp);
      element.addEventListener("pointercancel", handlePointerCancel);
      window.addEventListener("keydown", handleKeyDown);

      dragStateRef.current = {
        mode,
        pointerId: e.pointerId,
        element,
        originClientX,
        originTask,
        crossedThreshold: false,
        lastSnappedDeltaPx: 0,
        pendingDates: null,
        handlePointerMove,
        handlePointerUp,
        handlePointerCancel,
        handleKeyDown,
      };
    },
    [disabled, task.start_date, task.target_date, chart, laneMarginLeft, onCommit, cleanup]
  );

  return { onPointerDown, preview, isDragging, suppressClick };
}
