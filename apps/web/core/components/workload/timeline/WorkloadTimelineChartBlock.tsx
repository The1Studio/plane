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
import { periodDateRange } from "@plane/workload-ext";
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

    return (
      <div className="relative h-8 w-full">
        {data.tasks.map((task: TWorkloadTask) => {
          const start = task.start_date ?? task.target_date!;
          const startPos = getPositionFromDate(currentViewData, start, 0);
          // Land on the END of the target day, not its start — a bar for a
          // single-day task would otherwise have zero width.
          const endPos = getPositionFromDate(currentViewData, task.target_date!, dayWidth);
          const left = startPos - laneMarginLeft;
          const width = Math.max(endPos - startPos, 8);
          return (
            <WorkloadTaskLink
              key={task.id}
              task={task}
              workspaceSlug={workspaceSlug}
              className="absolute top-0 block h-8"
              style={{ left: `${left}px`, width: `${width}px` }}
            >
              <div
                className={cn(
                  "flex h-8 w-full cursor-pointer items-center truncate rounded-sm px-2 text-11 font-medium transition-colors",
                  task.overdue
                    ? "bg-danger-subtle text-danger-primary hover:bg-danger-subtle/80"
                    : "bg-accent-primary/15 text-accent-primary hover:bg-accent-primary/25"
                )}
                title={`${task.identifier} ${task.name} · ${task.hours}h${task.overdue ? " · overdue" : ""}`}
              >
                {/* Name and hours only. The identifier prefix ate a third of a
                    narrow bar's width without telling the reader anything they
                    could not get from hovering — it stays in the `title` above,
                    and in the sidebar cell for a single-task lane. */}
                <span className="truncate">
                  {task.name} · {task.hours}h
                </span>
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
