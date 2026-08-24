// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — chart-body renderer for
// one blockId (`blockToRender`, called once per block by `GanttChartBlock`
// via `ChartDraggable`). Branches on `data.kind`:
//
// - `task`  → a single positioned bar (core's existing block-position math
//   already placed it via `getItemPositionWidth`/`IGanttBlock.position` — this
//   only renders the bar's CONTENT, not its position).
// - `header` → the capacity heat row: N period cells positioned INSIDE the
//   header block's own box. The header block's `start_date`/`target_date`
//   (set in blocks.ts) span the WHOLE `periods[]` range, so its own
//   `position.marginLeft` is the pixel origin every period cell is offset
//   against — `getPositionFromDate` (the same helper `getItemPositionWidth`
//   itself calls) gives each period's ABSOLUTE offset from the chart's start;
//   subtracting the header block's own marginLeft converts that to a
//   position relative to this block's box, which is what its wrapper div's
//   `position: relative` coordinate system expects.

import { observer } from "mobx-react";
import { cn } from "@plane/utils";
import { hoursLabelStep, periodDateRange } from "@plane/workload-ext";
import type { TWorkloadGranularity, TWorkloadTask } from "@plane/workload-ext";
import { getPositionFromDate } from "@/components/gantt-chart/views";
import { useTimeLineChartStore } from "@/hooks/use-timeline-chart";
import { heatCellColorClass } from "./heat-color";
import { WorkloadTaskLink } from "./WorkloadTaskLink";
import type { TWorkloadTimelineBlockData } from "./types";

type Props = {
  data: TWorkloadTimelineBlockData;
  granularity: TWorkloadGranularity;
  workspaceSlug: string;
};

/**
 * Floor for a task bar's rendered width, in px.
 *
 * This is a DURATION floor, and only that: it exists so a bar can never be
 * drawn at zero width. It is deliberately no longer a label floor.
 *
 * It used to be 60px and it used to carry both jobs. The argument for 60 was
 * legibility: `hours` is a 2-decimal float (`quantize_hours` → `round(cents /
 * 100, 2)` in `plane/workload/aggregation.py`), so the widest realistic label
 * is `10.75h` — ~34px at `text-11`, plus 16px of `px-2` — and 60px was the
 * width at which that still rendered whole. The row is `overflow-hidden` and,
 * with no title beside it, `justify-center`, so a bar too narrow for its label
 * does not clip politely at the tail: it eats BOTH ends and `10.75h` renders
 * as a confident, wrong `0.75`.
 *
 * That guarantee has not been dropped, it has moved. `hoursLabelStep`
 * (`@plane/workload-ext`) now answers "does this label fit in this bar", and
 * steps `text-11` → `text-9` → no label at all rather than ever clipping. Its
 * unit tests pin the boundaries against the three `dayWidth` values below,
 * which is more than this constant's docstring could ever do.
 *
 * Which zooms this binds on — `dayWidth` is 180 at Week, 60 at Month, 30 at
 * Quarter (gantt-chart/data/index.ts). A bar is at minimum one full day wide,
 * so at Week (180px) and Month (60px) the true width already clears 30 and
 * nothing is distorted. It binds ONLY at Quarter, where it is now exactly one
 * day — so a 1-day task is drawn one day wide instead of the two days' worth
 * the old 60px floor inflated it to.
 *
 * That inflation was not free, which is the second reason for the change:
 * `packTasksIntoLanes` packs tasks into a lane by DATE and knows nothing about
 * rendered pixels, so a 1-day task stretched to two days could paint over the
 * task starting the next day in the same lane. Halving the floor strictly
 * reduces that overlap.
 */
const MIN_BAR_WIDTH = 30;

export const WorkloadTimelineChartBlock = observer(function WorkloadTimelineChartBlock({
  data,
  granularity,
  workspaceSlug,
}: Props) {
  const { currentViewData, getBlockById } = useTimeLineChartStore();

  if (data.kind === "lane") {
    // Every bar in the lane is positioned inside this block's own box, exactly
    // as the header row places its heat cells: `getPositionFromDate` gives an
    // ABSOLUTE offset from the chart's start, and subtracting the block's own
    // marginLeft converts it to this box's coordinate space.
    if (!currentViewData) return null;
    const laneBlock = getBlockById(data.id);
    const laneMarginLeft = laneBlock?.position?.marginLeft ?? 0;
    const dayWidth = currentViewData.data.dayWidth;
    // Week is the zoom read for DETAIL — which item, whose, how long — and it
    // has the pixels to answer all three: a bar is at least 180px, so it can
    // afford a second line carrying the work-item identifier.
    //
    // Month and Quarter are read for LOAD. There the name is the first thing
    // to go: at Month a bar is 60px per day and a name is two or three
    // characters before the ellipsis, which costs the width the estimate needs
    // and tells the reader nothing they could not get by hovering. Both zooms
    // therefore show the estimate alone, centred; the name and identifier stay
    // one hover away in the `title` below, which is now their ONLY home on
    // those zooms — the lane's sidebar cell is deliberately blank
    // (WorkloadTimelineSidebarRow), so do not let that tooltip decay.
    const isWeek = currentViewData.key === "week";
    // 40px inside core's 44px BLOCK_HEIGHT lane row. Verified against
    // gantt-chart/blocks/{block,block-row}.tsx: neither sets `overflow:
    // hidden`, and both set exactly BLOCK_HEIGHT, so the taller bar fits with
    // 4px to spare. If a core update ever adds `overflow-hidden` there, this
    // is the line that breaks.
    const barHeightClass = isWeek ? "h-10" : "h-8";

    return (
      // The container tracks the bar height rather than staying at h-8: the
      // bars inside are absolutely positioned and would overflow it silently,
      // which makes every later reader distrust the row alignment.
      <div className={cn("relative w-full", barHeightClass)}>
        {data.tasks.map((task: TWorkloadTask) => {
          const start = task.start_date ?? task.target_date!;
          const startPos = getPositionFromDate(currentViewData, start, 0);
          // Land on the END of the target day, not its start — a bar for a
          // single-day task would otherwise have zero width.
          const endPos = getPositionFromDate(currentViewData, task.target_date!, dayWidth);
          const left = startPos - laneMarginLeft;
          const width = Math.max(endPos - startPos, MIN_BAR_WIDTH);
          const hoursLabel = `${task.hours}h`;
          // Week bars are 180px at minimum and clear the ladder trivially, so
          // they are not run through it — otherwise a pathological label could
          // shrink the font on a bar with room to spare.
          const labelStep = isWeek ? "normal" : hoursLabelStep(width, hoursLabel);
          return (
            <WorkloadTaskLink
              key={task.id}
              task={task}
              workspaceSlug={workspaceSlug}
              className={cn("absolute top-0 block", barHeightClass)}
              style={{ left: `${left}px`, width: `${width}px` }}
            >
              <div
                className={cn(
                  "w-full cursor-pointer overflow-hidden rounded-sm font-medium transition-colors",
                  barHeightClass,
                  isWeek
                    ? // Two lines: identifier, then name + hours. `flex-col`
                      // keeps them as siblings so the identifier's own
                      // truncation cannot push the row below it around.
                      "flex flex-col justify-center px-2 text-11"
                    : // One line. With the name gone there is nothing to sit
                      // opposite, so the estimate centres rather than hugging
                      // an edge. Padding and font size come from the ladder:
                      // at 30px the small step has none to spare (see
                      // BAR_LABEL_STEPS.small).
                      cn(
                        "flex items-center justify-center",
                        labelStep === "normal" && "px-2 text-11",
                        labelStep === "small" && "px-0 text-9"
                      ),
                  task.overdue
                    ? "bg-danger-subtle text-danger-primary hover:bg-danger-subtle/80"
                    : "bg-accent-primary/15 text-accent-primary hover:bg-accent-primary/25"
                )}
                // The bar shows this member's SHARE. A work item can carry
                // several assignees (ClickUp parity) and its estimate is split
                // evenly across them, so a bar reading "4h" on a shared 8h task
                // is correct but looks wrong against the work item itself —
                // the tooltip spells the split out rather than leaving the
                // reader to think the estimate changed.
                title={`${task.identifier} ${task.name} · ${task.hours}h${
                  task.assignee_count > 1 ? ` of ${task.total_hours}h, split ${task.assignee_count} ways` : ""
                }${task.overdue ? " · overdue" : ""}`}
              >
                {isWeek ? (
                  <>
                    {/* The identifier is a lookup key, not the label, so it is
                        dimmed and set smaller — the eye should land on the
                        name. It gets its OWN truncation; sharing a text node
                        with the name would let one eat the other's ellipsis,
                        which is the same mistake the row below already
                        documents. */}
                    <span className="truncate text-9 leading-tight tabular-nums opacity-70">{task.identifier}</span>
                    <span className="flex items-center gap-1.5 leading-tight">
                      {/* These are two nodes on purpose — do NOT collapse them
                          back into one truncating span. Sharing a single text
                          node made the name and the hours compete for the same
                          ellipsis, and the name always won: a long title
                          clipped the estimate entirely. Now the name yields
                          (`min-w-0` is what lets a flex child shrink below its
                          content width and actually truncate) while the hours
                          never shrink, so `Nh` is the last thing standing on a
                          narrow bar. `gap-1.5` supplies the separation the old
                          `·` used to; `overflow-hidden` on the bar keeps a
                          shrunk name from bleeding past its edge. */}
                      <span className="min-w-0 flex-1 truncate">{task.name}</span>
                      <span className="shrink-0 tabular-nums">{hoursLabel}</span>
                    </span>
                  </>
                ) : (
                  // The estimate is the one element that survives every zoom —
                  // except where it cannot survive WHOLE. `hidden` renders a
                  // bare coloured bar rather than a partial number; the `title`
                  // above still carries the value, and a rounded or abbreviated
                  // stand-in would be the same lie in fewer characters.
                  labelStep !== "hidden" && <span className="tabular-nums">{hoursLabel}</span>
                )}
              </div>
            </WorkloadTaskLink>
          );
        })}
      </div>
    );
  }

  // footer — sidebar-only; the chart side of the strip is intentionally blank.
  if (data.kind === "footer") return <div className="h-8 w-full" />;

  // header — the capacity heat row.
  if (!currentViewData) return null;
  const block = getBlockById(data.id);
  const blockMarginLeft = block?.position?.marginLeft ?? 0;

  return (
    <div className="relative h-8 w-full">
      {data.periods.map((period: string) => {
        const { start, end } = periodDateRange(period, granularity);
        const startPos = getPositionFromDate(currentViewData, start, 0);
        // Land on the END of the last day in the period, not its start — an
        // `offsetWidth` of one full `dayWidth` pushes the right edge past
        // `end`'s own column instead of stopping at its left edge.
        const endPos = getPositionFromDate(currentViewData, end, currentViewData.data.dayWidth);
        const left = startPos - blockMarginLeft;
        const width = Math.max(endPos - startPos, 1);
        const hours = data.row.buckets[period] ?? 0;
        const capacity = data.row.capacity_buckets?.[period] ?? 0;
        const isOver = data.row.over?.[period] === true;
        return (
          <div
            key={period}
            className={cn(
              "absolute top-0 flex h-8 items-center justify-center border-r border-subtle text-11 tabular-nums",
              heatCellColorClass(hours, capacity, isOver)
            )}
            style={{ left: `${left}px`, width: `${width}px` }}
            title={`${period}: ${hours}h / ${capacity}h`}
          >
            {/* `0h`, not blank. Every period in the window now has a column
                (the API fills `periods` across the requested range), so an
                empty cell is a real measurement — rendering nothing there
                reads as "no data" instead of "no work booked". */}
            {`${hours}h`}
          </div>
        );
      })}
    </div>
  );
});
