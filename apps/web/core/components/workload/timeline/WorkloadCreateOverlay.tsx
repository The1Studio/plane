// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-5-click-to-create.md) — transparent
// click-to-create layer rendered inside the same "relative h-8 w-full" box
// WorkloadTimelineChartBlock's lane branch already renders the bars in.
//
// No explicit z-index war with the bars is needed: this component is mounted
// FIRST in that box's JSX (a sibling ahead of the `data.tasks.map(...)` bars)
// and neither this layer nor a bar sets a z-index, so plain DOM paint order
// alone puts every bar on top — a click landing on a bar's own pixels is
// handled by the bar (WorkloadTaskLink's ControlLink / drag handles) and never
// reaches this layer's onClick.
//
// Loosely mirrors core's ChartAddBlock affordance (gantt-chart/helpers/add-block.tsx
// — a "+" button following the cursor, with a date tooltip) without sharing its
// code: that component solves a different problem (scheduling an existing
// DATELESS block via blockUpdateHandler) and is unreachable here — see
// phase-5-click-to-create.md "Why core's ChartAddBlock is not the answer".
// Diverges from it on click-target SIZE: the clickable area here is the full
// day column (dayWidth wide, full lane height), not a small centred icon —
// a small target proved too easy to miss, especially at Week zoom's wide
// (180px) columns where the cursor could be far from a centred 32px button.

import { useState } from "react";
import { PlusIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import type { ChartDataType } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
import { wlt } from "@plane/workload-ext";
import { getDateFromPositionOnGantt, getPositionFromDate } from "@/components/gantt-chart/views";
import { usePlatformOS } from "@/hooks/use-platform-os";

/**
 * What a click asks WorkloadTimelineRoot to seed the create modal with. Only
 * the click's own day + the swimlane's assignee — WorkloadTimelineRoot derives
 * the rest (the one-day/one-week default span, `assignee_ids`) since that is
 * where the current zoom (for the quarter widening) is already read.
 */
export type TCreateSeed = { day: Date; assigneeId: string | null };

type Props = {
  chart: ChartDataType;
  /** The lane block's own pixel origin — same value WorkloadTimelineChartBlock
   *  passes to WorkloadTaskBar/useTaskBarDrag for this same box, so a click
   *  here resolves to the same date a bar dropped at this pixel would. */
  laneMarginLeft: number;
  /** `data.assigneeId` of the lane this overlay backs — `null` for Unassigned. */
  assigneeId: string | null;
  /**
   * Workspace-level "can create somewhere" gate (phase-5-click-to-create.md
   * "Permission") — a visibility check only. The create modal's own project
   * picker still enforces the real per-project right on submit; a `+` that
   * opens a modal with an empty project list would be worse than no `+`.
   */
  canCreate: boolean;
  onRequestCreate: (seed: TCreateSeed) => void;
};

export function WorkloadCreateOverlay({ chart, laneMarginLeft, assigneeId, canCreate, onRequestCreate }: Props) {
  const [hoverX, setHoverX] = useState<number | null>(null);
  const { isMobile } = usePlatformOS();

  if (!canCreate) return null;

  const dayWidth = chart.data.dayWidth;
  // ONE source of truth for the hovered day. The date the tooltip shows, the
  // date a click creates in, AND the column the clickable button spans are
  // all derived from this single value, and the button's own screen box is
  // re-derived from that SAME date (round-trip through `getPositionFromDate`),
  // so the button, its tooltip, and what a click creates can never disagree
  // with EACH OTHER — but all three could still disagree with the CURSOR.
  //
  // `getDateFromPositionOnGantt` rounds to the NEAREST day boundary — correct
  // for the drag/resize snapping it was written for (useTaskBarDrag.ts wants
  // "which grid line is closest"), wrong for "which day's CELL contains this
  // pixel": rounding's tie point sits at the column's MIDPOINT, so hovering
  // anywhere in the right half of day N's column already reports day N+1 —
  // the highlighted cell (and the cell a click creates in) visibly led the
  // cursor by up to half a `dayWidth`. Shifting the queried position left by
  // half a day before rounding turns that "nearest boundary" into "which
  // column contains this pixel" — `Math.round(v - 0.5) === Math.floor(v)` for
  // any real `v`, so this is an exact floor, not an approximation, achieved
  // by reusing the existing helper rather than duplicating its date-stepping.
  const hoveredDay = hoverX !== null ? getDateFromPositionOnGantt(hoverX + laneMarginLeft - dayWidth / 2, chart) : null;
  const columnLeft = hoveredDay ? getPositionFromDate(chart, hoveredDay, 0) - laneMarginLeft : 0;

  // The div itself stays non-interactive — it only ever tracks the pointer
  // (onMouseMove/onMouseLeave) — so it needs no `role`/keyboard handler of
  // its own; the actual affordance is a real, natively keyboard-operable
  // `<button>` that spans the hovered day's full column (below). Mirrors
  // core's ChartAddBlock, whose own tracking div carries no onClick at all;
  // only its button does.
  const handleCreateClick = () => {
    if (!hoveredDay) return;
    onRequestCreate({ day: hoveredDay, assigneeId });
  };

  // `e.currentTarget` (this div, guaranteed by React regardless of which
  // descendant the pointer is actually over) + `clientX` minus the div's own
  // bounding-rect left, NOT `e.nativeEvent.offsetX`. `offsetX` is relative to
  // `e.target` — the actual innermost element under the cursor — so the
  // instant the pointer entered the clickable button's own box (now a good
  // chunk of the lane, not a small icon), `hoverX` would jump to being
  // relative to the BUTTON's own frame instead of this div, corrupting
  // `hoveredDay` right where the cursor already is. This computation is
  // immune to that: it is the same value no matter which child (if any) is
  // under the pointer.

  return (
    <Tooltip
      tooltipContent={hoveredDay ? renderFormattedDate(hoveredDay) : ""}
      isMobile={isMobile}
      // The Tooltip's Trigger merges its hover/focus handlers onto its child
      // — attached to THIS div (which always receives pointer events, unlike
      // the old small icon-only button that briefly went pointer-events-none)
      // so the tooltip opens the instant a lane is hovered, everywhere in it.
      // The tooltip content is only rendered when there is a hovered day; an
      // empty string keeps the Tooltip component inert when the cursor is
      // outside this lane.
      disabled={!hoveredDay}
    >
      <div
        className="absolute inset-0 z-0"
        onMouseMove={(e) => setHoverX(e.clientX - e.currentTarget.getBoundingClientRect().left)}
        onMouseLeave={() => setHoverX(null)}
      >
        {hoveredDay && (
          <button
            type="button"
            aria-label={wlt("timeline.create_work_item")}
            onClick={handleCreateClick}
            // The clickable area is the FULL day column, not a small icon
            // centred in it — one `dayWidth` wide, full lane height, so a
            // click anywhere in the hovered day's cell creates there. The
            // "+" icon inside is purely a visual affordance; it does not
            // define the hit area (that was the earlier, more fragile
            // design: a 32x32 target easy to miss, and offset from wherever
            // the cursor actually was within a wide Week-zoom column).
            className="absolute inset-y-0 flex items-center justify-center rounded-sm border border-transparent text-secondary transition-colors hover:border-strong hover:bg-layer-1"
            style={{ left: `${columnLeft}px`, width: `${dayWidth}px` }}
          >
            <PlusIcon className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </Tooltip>
  );
}
