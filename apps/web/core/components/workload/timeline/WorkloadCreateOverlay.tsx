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
// Mirrors core's ChartAddBlock affordance shape (gantt-chart/helpers/add-block.tsx
// — a bordered 32px "+" button following the cursor, with a date tooltip)
// without sharing its code: that component solves a different problem
// (scheduling an existing DATELESS block via blockUpdateHandler) and is
// unreachable here — see phase-5-click-to-create.md "Why core's ChartAddBlock
// is not the answer".

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
  // date a click creates in, AND the column the "+" button snaps to are all
  // derived from this single value. Previously the button snapped with
  // `Math.floor(hoverX / dayWidth)` while `getDateFromPositionOnGantt` rounds
  // with `Math.round`, so past a column's midpoint the tooltip/created-item
  // advanced to day N+1 while the button stayed centred on day N — clicking
  // the visible "+" reliably created on the wrong day (B2). Now the button's
  // snapped screen position is re-derived from the SAME date (round-trip
  // through `getPositionFromDate`), so the button, its tooltip, and what a
  // click creates are always in agreement.
  const hoveredDay = hoverX !== null ? getDateFromPositionOnGantt(hoverX + laneMarginLeft, chart) : null;
  const columnLeft = hoveredDay ? getPositionFromDate(chart, hoveredDay, 0) - laneMarginLeft : 0;

  // Click lands on the "+" button, not this whole tracking layer (below) — the
  // button already re-derives its screen position from `hoveredDay` (see the
  // comment above), so reusing that same value here keeps click, tooltip, and
  // button position all in agreement with zero extra pixel math. This also
  // keeps the div itself non-interactive: it only ever tracks the pointer
  // (onMouseMove/onMouseLeave), so it needs no `role`/keyboard handler of its
  // own — the actual affordance is a real, natively keyboard-operable
  // `<button>`. Mirrors core's ChartAddBlock, whose own tracking div carries
  // no onClick at all; only its button does.
  const handleCreateClick = () => {
    if (!hoveredDay) return;
    onRequestCreate({ day: hoveredDay, assigneeId });
  };

  // `e.currentTarget` (this div, guaranteed by React regardless of which
  // descendant the pointer is actually over) + `clientX` minus the div's own
  // bounding-rect left, NOT `e.nativeEvent.offsetX`. `offsetX` is relative to
  // `e.target` — the actual innermost element under the cursor — so the
  // instant the pointer entered the "+" button's own box, `hoverX` would jump
  // to being relative to the BUTTON's tiny 32px frame instead of this div,
  // corrupting `hoveredDay` right where a user naturally rests the cursor to
  // click it. This computation is immune to that: it is the same value no
  // matter which child (if any) is under the pointer.

  return (
    <Tooltip
      tooltipContent={hoveredDay ? renderFormattedDate(hoveredDay) : ""}
      isMobile={isMobile}
      // The Tooltip's Trigger merges its hover/focus handlers onto its child.
      // The "+" button below is `pointer-events-none` (load-bearing — it keeps
      // `nativeEvent.offsetX` on click resolving against THIS div, not the
      // button), so a `pointer-events: none` element is never a hit-test
      // target and the tooltip would never open if the Trigger wrapped it
      // (B3). Attaching the Tooltip to THIS div instead — which does receive
      // pointer events — is what lets the date tooltip show on hover while
      // the button stays non-interactive for offsetX correctness.
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
            // Mouse-clickable: `hoverX` above no longer depends on `e.target`,
            // so the button no longer needs `pointer-events-none` to protect
            // it — that class previously made the button impossible to
            // MOUSE-click at all (pointer-events:none blocks hit-testing
            // outright; only keyboard activation, which bypasses hit-testing,
            // ever reached its onClick). Real, natively keyboard-operable too.
            className="absolute top-1/2 grid h-8 w-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-sm border border-strong bg-layer-1 p-1.5 text-secondary"
            style={{ left: `${columnLeft + dayWidth / 2}px` }}
          >
            <PlusIcon className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </Tooltip>
  );
}
