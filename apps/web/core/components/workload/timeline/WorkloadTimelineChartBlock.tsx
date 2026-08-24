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

import { useCallback } from "react";
import { observer } from "mobx-react";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import type { ChartDataType } from "@plane/types";
import { cn } from "@plane/utils";
import { hoursLabelStep, periodDateRange, wlt } from "@plane/workload-ext";
import type { TWorkloadGranularity, TWorkloadTask } from "@plane/workload-ext";
import { getPositionFromDate } from "@/components/gantt-chart/views";
import { useUserPermissions } from "@/hooks/store/user";
import { useTimeLineChartStore } from "@/hooks/use-timeline-chart";
import { heatCellColorClass } from "./heat-color";
import type { TDraggedDates } from "./useTaskBarDrag";
import { useTaskBarDrag } from "./useTaskBarDrag";
import type { TCreateSeed } from "./WorkloadCreateOverlay";
import { WorkloadCreateOverlay } from "./WorkloadCreateOverlay";
import { WorkloadTaskLink } from "./WorkloadTaskLink";
import type { TWorkloadTimelineBlockData } from "./types";

type Props = {
  data: TWorkloadTimelineBlockData;
  granularity: TWorkloadGranularity;
  workspaceSlug: string;
  /** The real write path (phase-4-write-path.md), threaded down from
   *  WorkloadTimelineRoot — patches the store optimistically, then
   *  `patchIssue`s, rolling back and toasting on failure. */
  onCommitDates: (task: TWorkloadTask, dates: TDraggedDates) => void;
  /** phase-5-click-to-create.md "Permission" — workspace-level "can create
   *  somewhere" gate for the empty-space overlay's own visibility. */
  canCreateAnywhere: boolean;
  /** phase-5-click-to-create.md — a click on empty lane space asks
   *  WorkloadTimelineRoot to open the (single, root-mounted) create modal. */
  onRequestCreate: (seed: TCreateSeed) => void;
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

/**
 * Width of each resize-handle strip, in px (phase-3-bar-wiring.md "Handles").
 * `w-1.5` in Tailwind's default 4px scale.
 */
const HANDLE_WIDTH_PX = 6;

/**
 * Below this much remaining body (bar width minus both handles), the left
 * handle is dropped and only the right one renders — resizing the end is the
 * common operation, and a bar with two handles and no body left is not
 * draggable at all (phase-3-bar-wiring.md "Handles").
 */
const MIN_BODY_WITH_BOTH_HANDLES_PX = 24;

type WorkloadTaskBarProps = {
  task: TWorkloadTask;
  workspaceSlug: string;
  chart: ChartDataType;
  laneMarginLeft: number;
  dayWidth: number;
  onCommitDates: (task: TWorkloadTask, dates: TDraggedDates) => void;
  /**
   * Render as an UNSCHEDULED placeholder: dashed outline, no fill.
   *
   * The caller passes a SYNTHETIC one-day task at the anchor column (see the
   * `kind: "unscheduled"` branch below), which is what lets this component and
   * `useTaskBarDrag` stay completely unaware that the real work item has no
   * dates. Only the styling and the tooltip differ; the drag, the resize, the
   * permission gate and the label ladder are the same code paths.
   */
  unscheduled?: boolean;
};

/**
 * One draggable/resizable bar inside a `kind: "lane"` block. Pulled out of the
 * lane's `.map()` because `useUserPermissions`/`useTaskBarDrag` are hooks and
 * hooks cannot be called from inside a `.map()` callback — each bar needs its
 * own hook instance (phase-3-bar-wiring.md "Where the code goes").
 */
const WorkloadTaskBar = observer(function WorkloadTaskBar({
  task,
  workspaceSlug,
  chart,
  laneMarginLeft,
  dayWidth,
  onCommitDates,
  unscheduled = false,
}: WorkloadTaskBarProps) {
  const { allowPermissions } = useUserPermissions();

  // D4 — gated per BAR on that task's OWN project, never the board's. A single
  // swimlane routinely mixes projects, and `allowPermissions` needs an
  // explicit `projectId` since this route has no `:projectId` param of its own.
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    task.project_id
  );

  const handleCommit = useCallback(
    (dates: TDraggedDates) => {
      onCommitDates(task, dates);
    },
    [task, onCommitDates]
  );

  const { onPointerDown, preview, isDragging, suppressClick } = useTaskBarDrag({
    task,
    chart,
    laneMarginLeft,
    disabled: !canEdit,
    onCommit: handleCommit,
  });

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
  const isWeek = chart.key === "week";
  // 40px inside core's 44px BLOCK_HEIGHT lane row. Verified against
  // gantt-chart/blocks/{block,block-row}.tsx: neither sets `overflow:
  // hidden`, and both set exactly BLOCK_HEIGHT, so the taller bar fits with
  // 4px to spare. If a core update ever adds `overflow-hidden` there, this
  // is the line that breaks.
  const barHeightClass = isWeek ? "h-10" : "h-8";

  const start = task.start_date ?? task.target_date!;
  const startPos = getPositionFromDate(chart, start, 0);
  // Land on the END of the target day, not its start — a bar for a
  // single-day task would otherwise have zero width.
  const endPos = getPositionFromDate(chart, task.target_date!, dayWidth);

  // Note the asymmetry: `MIN_BAR_WIDTH` is applied to the committed (non-drag)
  // position but NOT to `preview` — during a resize the user is setting a
  // real duration and must see it; clamping the preview to the floor would
  // show a longer bar while they drag out a shorter one. The floor returns on
  // the next render from committed data (phase-3-bar-wiring.md "Applying the
  // preview").
  const left = preview ? preview.left : startPos - laneMarginLeft;
  const width = preview ? preview.width : Math.max(endPos - startPos, MIN_BAR_WIDTH);
  // The COMMITTED width — the bar's last non-preview geometry, always at least
  // `MIN_BAR_WIDTH`. Handle visibility is derived from THIS, never from the live
  // `preview.width`: during a left-edge resize at quarter zoom a one-day preview
  // can drop below `MIN_BODY_WITH_BOTH_HANDLES_PX` once both handles are paid
  // for. If `showLeftHandle` tracked the preview, React would unmount the very
  // handle the pointer is captured on mid-drag, the pointerup/pointercancel
  // listeners bound to that element would never fire, `dragStateRef` would
  // never clear, and the bar would freeze permanently (B1). `isDragging` keeps
  // the handle mounted for the duration of the gesture regardless of preview
  // width.
  const committedWidth = Math.max(endPos - startPos, MIN_BAR_WIDTH);

  const hoursLabel = `${task.hours}h`;
  // Week bars are 180px at minimum and clear the ladder trivially, so they
  // are not run through it — otherwise a pathological label could shrink the
  // font on a bar with room to spare. Stepped against the LIVE width (preview
  // during a drag, committed otherwise) so the label keeps pace with the bar
  // the user is actually looking at instead of jumping on drop.
  const labelStep = isWeek ? "normal" : hoursLabelStep(width, hoursLabel);

  const showRightHandle = canEdit;
  const showLeftHandle =
    canEdit && (committedWidth - 2 * HANDLE_WIDTH_PX >= MIN_BODY_WITH_BOTH_HANDLES_PX || isDragging);

  const handleResizeStartPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    e.preventDefault();
    onPointerDown(e, "resize-start");
  };
  const handleResizeEndPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    e.preventDefault();
    onPointerDown(e, "resize-end");
  };
  const handleBodyPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    // Same native-drag concern as the handles below — `preventDefault` keeps
    // the browser from starting a text selection instead of handing
    // pointermove events to the drag hook.
    e.preventDefault();
    onPointerDown(e, "move");
  };

  return (
    <WorkloadTaskLink
      task={task}
      workspaceSlug={workspaceSlug}
      className={cn("group absolute top-0 block", barHeightClass)}
      style={{ left: `${left}px`, width: `${width}px` }}
      suppressClick={suppressClick}
    >
      <div
        className={cn(
          "w-full overflow-hidden rounded-sm font-medium transition-colors",
          barHeightClass,
          // Without this, a horizontal pointerdown-drag on a touchscreen or
          // trackpad can be claimed by the browser's own pan/scroll gesture
          // recognizer before our pointermove listener ever sees a second
          // event — the gesture becomes a native scroll instead of a drag,
          // silently, with no error to report. `touch-action: none` is what
          // tells the browser this element owns its own pointer gestures.
          canEdit && "touch-none",
          canEdit ? (isDragging ? "cursor-grabbing" : "cursor-grab") : "cursor-pointer",
          isWeek
            ? // Two lines: identifier, then name + hours. `flex-col` keeps
              // them as siblings so the identifier's own truncation cannot
              // push the row below it around.
              "flex flex-col justify-center px-2 text-11"
            : // One line. With the name gone there is nothing to sit opposite,
              // so the estimate centres rather than hugging an edge. Padding
              // and font size come from the ladder: at the smallest step
              // there is none to spare (see BAR_LABEL_STEPS.small).
              cn(
                "flex items-center justify-center",
                labelStep === "normal" && "px-2 text-11",
                labelStep === "small" && "px-0 text-9"
              ),
          // A dashed, unfilled outline is the whole signal that this bar is a
          // PLACEHOLDER occupying a column rather than a span covering it. A
          // solid bar sitting in today's column reads as "due today", which is
          // a claim the data does not make. An unscheduled task is never
          // `overdue` — the API requires a non-null target for that flag — so
          // there is no red branch to reach here.
          unscheduled
            ? "border-tertiary hover:border-secondary hover:bg-tertiary/10 border border-dashed bg-transparent text-tertiary"
            : task.overdue
              ? "bg-danger-subtle text-danger-primary hover:bg-danger-subtle/80"
              : "bg-accent-primary/15 text-accent-primary hover:bg-accent-primary/25"
        )}
        onPointerDown={handleBodyPointerDown}
        // The bar shows this member's SHARE. A work item can carry
        // several assignees (ClickUp parity) and its estimate is split
        // evenly across them, so a bar reading "4h" on a shared 8h task
        // is correct but looks wrong against the work item itself —
        // the tooltip spells the split out rather than leaving the
        // reader to think the estimate changed.
        // The unscheduled disclaimer is the ONLY place a reader learns why this
        // bar's `4h` is absent from the heat cell directly beneath it: the API
        // routes an unscheduled estimate to its own `unscheduled` bucket and
        // never into `buckets`, deliberately, so the two genuinely disagree.
        title={`${task.identifier} ${task.name} · ${task.hours}h${
          task.assignee_count > 1 ? ` of ${task.total_hours}h, split ${task.assignee_count} ways` : ""
        }${unscheduled ? ` · ${wlt("timeline.unscheduled_bar_title")}` : ""}${
          task.overdue ? " · overdue" : ""
        }${canEdit ? ` · ${wlt("timeline.drag_to_reschedule")}` : ""}`}
      >
        {isWeek ? (
          <>
            {/* The identifier is a lookup key, not the label, so it is
                dimmed and set smaller — the eye should land on the name. It
                gets its OWN truncation; sharing a text node with the name
                would let one eat the other's ellipsis, which is the same
                mistake the row below already documents. */}
            <span className="truncate text-9 leading-tight tabular-nums opacity-70">{task.identifier}</span>
            <span className="flex items-center gap-1.5 leading-tight">
              {/* These are two nodes on purpose — do NOT collapse them back
                  into one truncating span. Sharing a single text node made
                  the name and the hours compete for the same ellipsis, and
                  the name always won: a long title clipped the estimate
                  entirely. Now the name yields (`min-w-0` is what lets a
                  flex child shrink below its content width and actually
                  truncate) while the hours never shrink, so `Nh` is the last
                  thing standing on a narrow bar. `gap-1.5` supplies the
                  separation the old `·` used to; `overflow-hidden` on the
                  bar keeps a shrunk name from bleeding past its edge. */}
              <span className="min-w-0 flex-1 truncate">{task.name}</span>
              <span className="shrink-0 tabular-nums">{hoursLabel}</span>
            </span>
          </>
        ) : (
          // The estimate is the one element that survives every zoom — except
          // where it cannot survive WHOLE. `hidden` renders a bare coloured
          // bar rather than a partial number; the `title` above still carries
          // the value, and a rounded or abbreviated stand-in would be the
          // same lie in fewer characters.
          labelStep !== "hidden" && <span className="tabular-nums">{hoursLabel}</span>
        )}
      </div>
      {/* Handles sit above the ControlLink's own hit area (z-10 vs. the
          body's auto stacking) and stop/prevent their own pointerdown so a
          resize never also starts a native anchor drag or bubbles into a
          "move". Below `MIN_BODY_WITH_BOTH_HANDLES_PX` of remaining body the
          left handle is dropped — resizing the end is the common operation,
          and two handles with no body between them isn't draggable at all. */}
      {showLeftHandle && (
        <div
          tabIndex={0}
          title={wlt("timeline.resize_start")}
          // touch-none — see the content div's comment above; a resize handle
          // is even narrower (6px) than the bar body, so it is the likeliest
          // place for the browser to mistake a horizontal drag for a scroll.
          className="absolute inset-y-0 left-0 z-10 w-1.5 cursor-ew-resize touch-none opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          onPointerDown={handleResizeStartPointerDown}
        />
      )}
      {showRightHandle && (
        <div
          tabIndex={0}
          title={wlt("timeline.resize_end")}
          className="absolute inset-y-0 right-0 z-10 w-1.5 cursor-ew-resize touch-none opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          onPointerDown={handleResizeEndPointerDown}
        />
      )}
    </WorkloadTaskLink>
  );
});

export const WorkloadTimelineChartBlock = observer(function WorkloadTimelineChartBlock({
  data,
  granularity,
  workspaceSlug,
  onCommitDates,
  canCreateAnywhere,
  onRequestCreate,
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
    // The container tracks the bar height rather than staying fixed: bars
    // inside are absolutely positioned and would overflow it silently at
    // Week zoom's taller row, which makes every later reader distrust the
    // row alignment. `WorkloadTaskBar` derives the same `isWeek`/height class
    // itself from `chart.key`, so the two stay in step without a prop.
    const barHeightClass = currentViewData.key === "week" ? "h-10" : "h-8";

    return (
      <div className={cn("relative w-full", barHeightClass)}>
        {/* Mounted BEFORE the bars below — see this file's header comment for
            why plain DOM order, with no z-index on either side, already keeps
            a bar's own click from reaching this layer. */}
        <WorkloadCreateOverlay
          chart={currentViewData}
          laneMarginLeft={laneMarginLeft}
          assigneeId={data.assigneeId}
          canCreate={canCreateAnywhere}
          onRequestCreate={onRequestCreate}
        />
        {data.tasks.map((task: TWorkloadTask) => (
          <WorkloadTaskBar
            key={task.id}
            task={task}
            workspaceSlug={workspaceSlug}
            chart={currentViewData}
            laneMarginLeft={laneMarginLeft}
            dayWidth={dayWidth}
            onCommitDates={onCommitDates}
          />
        ))}
      </div>
    );
  }

  if (data.kind === "unscheduled") {
    if (!currentViewData) return null;
    const block = getBlockById(data.id);
    const marginLeft = block?.position?.marginLeft ?? 0;
    const barHeightClass = currentViewData.key === "week" ? "h-10" : "h-8";

    // A SYNTHETIC one-day task at the anchor column. The real work item has no
    // `target_date` — that is what makes it unscheduled — and every consumer
    // below (`WorkloadTaskBar`, `useTaskBarDrag`, the label ladder) is written
    // against a task that HAS one. Handing them a dated stand-in is what lets
    // the whole drag/resize/permission path be reused verbatim instead of
    // growing a null-date branch through three layers.
    //
    // Only the DATES are synthetic. `id`, `project_id` and `hours` are the real
    // ones, so the commit patches the right issue and the rollback snapshot —
    // read from the store, not from this object — restores the true nulls.
    const synthetic: TWorkloadTask = {
      ...data.task,
      start_date: data.anchorDate,
      target_date: data.anchorDate,
    };

    return (
      <div className={cn("relative w-full", barHeightClass)}>
        <WorkloadTaskBar
          task={synthetic}
          workspaceSlug={workspaceSlug}
          chart={currentViewData}
          laneMarginLeft={marginLeft}
          dayWidth={currentViewData.data.dayWidth}
          onCommitDates={onCommitDates}
          unscheduled
        />
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
