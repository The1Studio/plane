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

/**
 * Floor for a task bar's rendered width, in px.
 *
 * A bar must stay wide enough to render its `Nh` estimate WHOLE — that number
 * is the point of this view, and the hours span below is `shrink-0` inside an
 * `overflow-hidden` row, so a bar too narrow for it clips the number's TAIL:
 * `10.75h` renders as a confident, wrong `10.7`. A missing label is recoverable
 * (the `title` still carries the value); a truncated one is a lie.
 *
 * Sized against the widest realistic label rather than the common one, because
 * `hours` is a 2-decimal float (`quantize_hours` → `round(cents / 100, 2)` in
 * `plane/workload/aggregation.py`), not an integer: `10.75h` is ~34px at
 * `text-11`, and the row spends 16px on `px-2` plus 6px on `gap-1.5`. 60px
 * leaves ~38px of label room, which covers every estimate short of a
 * three-digit decimal.
 *
 * Which zooms this actually binds on — `dayWidth` is 180 at Week, 60 at Month,
 * 30 at Quarter (gantt-chart/data/index.ts). A bar is at minimum one full day
 * wide, so at Week and Month the true width already clears this floor and
 * nothing is distorted. It binds ONLY at Quarter zoom, and only on a 1-day
 * task, which is drawn 60px — 2 days' worth; a 2-day task already sits exactly
 * on the floor. That is a deliberate trade: at Quarter zoom the timeline is
 * read for load, not for duration, and an always-legible estimate is worth
 * more there than an exact sliver.
 *
 * Keep this paragraph in step with `VIEWS_LIST` — widening a zoom's `dayWidth`
 * shrinks how far this floor reaches, and the numbers above are the only place
 * that relationship is written down.
 */
const MIN_BAR_WIDTH = 60;

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
          const width = Math.max(endPos - startPos, MIN_BAR_WIDTH);
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
                  "flex h-8 w-full cursor-pointer items-center gap-1.5 overflow-hidden rounded-sm px-2 text-11 font-medium transition-colors",
                  task.overdue
                    ? "bg-danger-subtle text-danger-primary hover:bg-danger-subtle/80"
                    : "bg-accent-primary/15 text-accent-primary hover:bg-accent-primary/25"
                )}
                title={`${task.identifier} ${task.name} · ${task.hours}h${task.overdue ? " · overdue" : ""}`}
              >
                {/* Name and hours only. The identifier prefix ate a third of a
                    narrow bar's width without telling the reader anything they
                    could not get from hovering — it stays in the `title` above,
                    and in the sidebar cell for a single-task lane.

                    These are two nodes on purpose — do NOT collapse them back
                    into one truncating span. Sharing a single text node made
                    the name and the hours compete for the same ellipsis, and
                    the name always won: a long title clipped the estimate
                    entirely. Now the title yields (`min-w-0` is what lets a
                    flex child shrink below its content width and actually
                    truncate) while the hours never shrink, so `Nh` is the last
                    thing standing on a narrow bar. `gap-1.5` supplies the
                    separation the old `·` used to; `overflow-hidden` on the
                    row keeps a shrunk title from bleeding past the bar edge. */}
                <span className="min-w-0 flex-1 truncate">{task.name}</span>
                <span className="shrink-0 tabular-nums">{task.hours}h</span>
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
