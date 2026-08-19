// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — replaces the deleted
// aggregate `<Table>` view with per-assignee swimlanes of task bars, built on
// core's gantt-chart primitives.
//
// COMPOSITION DECISION (D12, evidence for the "did you have to edit
// ChartViewRoot?" call): NO edits to ChartViewRoot / GanttChartMainContent /
// GanttChartSidebar / GanttChartBlocksList / GanttChartRowList. Those own the
// zoom/pan state machine (`updateCurrentViewRenderPayload` — infinite
// horizontal-scroll pagination, the "today" jump, the week/month/quarter
// switch) as PRIVATE, unexported logic inside ChartViewRoot; duplicating it
// would mean re-deriving day-axis pagination and today-scroll math with no
// access to a browser to verify against, for logic the plan explicitly calls
// out as reusable. Composition instead happens ONE LAYER UP: `GanttChartRoot`
// is used wholesale (unmodified), fed a flat, ordered `blockIds` list where
// each swimlane is a RUN of one `header` block (capacity heat row) followed
// by that assignee's `task` blocks (see `blocks.ts`). `blockToRender` /
// `sidebarToRender` branch on the block's `kind` to render either shape.
// bulk-select / dependency-path / drag-reorder decorations that
// GanttChartMainContent renders unconditionally around blockToRender/
// sidebarToRender are inert no-ops here (`enableSelection`/`enableDependency`/
// `enableReorder` are all `false`, per D14 — see GanttChartRoot props below).
//
// This DOES need one small, additive registration: a dedicated
// `GANTT_TIMELINE_TYPE.WORKLOAD` MobX timeline-store instance (added to the
// EXTENDED_GANTT_TIMELINE_TYPE seam in packages/types — see extended.ts),
// fed via `updateBlocks` from an `autorun` below instead of the ISSUE/MODULE
// stores' own internal autorun (there's no single app-wide issue/module
// store to read from — the source is @plane/workload-ext's own MobX store).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { autorun, reaction } from "mobx";
import { observer } from "mobx-react";
import { GANTT_TIMELINE_TYPE } from "@plane/types";
import type { IBlockUpdateData, TGanttViews } from "@plane/types";
import type { IWorkloadStore, TWorkloadGranularity } from "@plane/workload-ext";
import { clampDateRange, wlt } from "@plane/workload-ext";
import { TimeLineTypeContext } from "@/components/gantt-chart/contexts";
import { GanttChartRoot } from "@/components/gantt-chart/root";
import { useTimeLineChart } from "@/hooks/use-timeline-chart";
import { BaseTimeLineStore } from "@/plane-web/store/timeline/base-timeline.store";
import { buildWorkloadBlocks, focusWeekKey } from "./blocks";
import { WorkloadTaskLink } from "./WorkloadTaskLink";
import { WorkloadTimelineChartBlock } from "./WorkloadTimelineChartBlock";
import { WorkloadTimelineSidebarRow } from "./WorkloadTimelineSidebarRow";
import type { TWorkloadTimelineBlockData } from "./types";

type Props = {
  store: IWorkloadStore;
  /** Passed down rather than re-read from `useParams` — the route page already has it. */
  workspaceSlug: string;
};

/**
 * The chart's zoom level IS the granularity control (phase-2.md D3).
 *
 * Before this, the page carried two time-range controls that could not agree:
 * the toolbar's Day/Week/Month set the SERVER-SIDE bucketing while
 * `GanttChartHeader`'s Week/Month/Quarter set the PIXEL ZOOM, and nothing kept
 * them in step — picking "Month" on one did nothing to the other. The toolbar
 * tabs are gone; this maps the surviving control onto the bucketing.
 *
 * The pairing is by COLUMN RESOLUTION, not by label. `VIEWS_LIST`
 * (components/gantt-chart/data) gives the `week` view a `dayWidth` of 60 with
 * per-day labels, `month` 20, and `quarter` 5 — so gantt-`week` is the only
 * view whose columns can legibly host per-day heat cells, and it is therefore
 * the view that pairs with `day` bucketing.
 *
 * The INITIAL pair is aligned in the workload store's own default
 * (`granularity = "day"` against `BaseTimeLineStore`'s `currentView = "week"`),
 * not by a mount effect here — see that field's comment for why a parent-side
 * sync cannot work. This map therefore only has to handle CHANGES.
 */
const VIEW_TO_GRANULARITY: Record<TGanttViews, TWorkloadGranularity> = {
  week: "day",
  month: "week",
  quarter: "month",
};

const noopBlockUpdateHandler = (_block: unknown, _payload: IBlockUpdateData) => {
  // Drag/resize/reorder are all disabled (D14, out of scope) — GanttChartRoot
  // still requires a handler prop, but it is never invoked.
};

export const WorkloadTimelineRoot = observer(function WorkloadTimelineRoot({ store, workspaceSlug }: Props) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  // `useTimeLineChart` is typed to return the `IBaseTimelineStore` interface
  // (shared by every timeline type), but `getTimelineStore` (ce/hooks/use-timeline-chart.ts)
  // resolves GANTT_TIMELINE_TYPE.WORKLOAD to a genuine `BaseTimeLineStore` instance
  // (ce/store/timeline/index.ts) — cast to reach `updateBlocks`, its one public
  // method the interface doesn't carry (only the ISSUE/MODULE stores' own
  // internal autorun calls it today).
  const timelineStore = useTimeLineChart(GANTT_TIMELINE_TYPE.WORKLOAD) as BaseTimeLineStore;

  const toggleCollapse = useCallback((key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const { blockIds, dataById } = useMemo(() => {
    if (!store.workloadData)
      return { blockIds: [] as string[], dataById: {} as Record<string, TWorkloadTimelineBlockData> };
    return buildWorkloadBlocks(store.workloadData, store.granularity, collapsed, store.showOverCapacityOnly);
  }, [store.workloadData, store.granularity, collapsed, store.showOverCapacityOnly]);

  // The week the badge reports on. Derived from the response itself, so it can
  // never index `weekly_buckets` with a key built from a different week-start
  // convention than the server used.
  const focusWeek = useMemo(() => (store.workloadData ? focusWeekKey(store.workloadData) : ""), [store.workloadData]);

  // `dataById` is a plain object, not a MobX observable — the autorun below
  // can't track it directly, so it's read through a ref updated every render.
  const dataByIdRef = useRef(dataById);
  dataByIdRef.current = dataById;

  useEffect(() => {
    timelineStore.setBlockIds(blockIds);
  }, [timelineStore, blockIds]);

  // Mirrors IssuesTimeLineStore's own pattern (store/timeline/issues-timeline.store.ts):
  // `updateBlocks` reads `this.blockIds` and `this.currentViewData` — both MobX
  // observables — so autorun re-fires on every blockIds change (see effect
  // above) AND on every pan/zoom-driven currentViewData change, keeping every
  // block's `position` current without a React re-render in the loop.
  useEffect(() => autorun(() => timelineStore.updateBlocks((id: string) => dataByIdRef.current[id])), [timelineStore]);

  // The chart's zoom is the granularity control: re-bucket and refetch when it
  // changes. `reaction` (not `autorun`) so this never fires on the initial
  // read — the two already agree at construction.
  useEffect(
    () =>
      reaction(
        () => timelineStore.currentView,
        (view: TGanttViews) => {
          const next = VIEW_TO_GRANULARITY[view];
          if (!next || next === store.granularity) return;
          store.setGranularity(next);
          // Load-bearing, not defensive: the API REJECTS an over-long span with
          // a 400 rather than truncating it (views.py `_SPAN_CAPS`, mirrored by
          // MAX_SPAN_DAYS). Zooming out to quarter and back in would otherwise
          // carry a 730-day range into a 92-day cap and break the page. Anchor
          // on "from" so the window keeps its start and gives up its tail.
          const { from, to } = clampDateRange(store.dateFrom, store.dateTo, next, "from");
          if (from !== store.dateFrom || to !== store.dateTo) store.setDateRange(from, to);
          store.fetchWorkload(workspaceSlug);
        }
      ),
    [timelineStore, store, workspaceSlug]
  );

  if (store.isLoading) {
    return <div className="py-8 text-center text-13 text-tertiary">{wlt("common.loading")}</div>;
  }
  if (store.error) {
    return <div className="py-4 text-13 text-danger-primary">{store.error}</div>;
  }
  if (!store.workloadData || store.workloadData.rows.length === 0) {
    return <div className="py-8 text-center text-13 text-placeholder">{wlt("timeline.no_workload_data")}</div>;
  }
  // There IS data — the over-capacity filter just excluded every swimlane.
  // Distinguishing the two matters: an empty chart under an active filter is a
  // result, not an absence, and rendering the generic "no workload data" here
  // would send the reader looking for a problem that does not exist.
  if (blockIds.length === 0) {
    return <div className="py-8 text-center text-13 text-placeholder">{wlt("timeline.no_over_capacity")}</div>;
  }

  const granularity = store.granularity;

  return (
    <TimeLineTypeContext.Provider value={GANTT_TIMELINE_TYPE.WORKLOAD}>
      <div className="h-[70vh] w-full">
        <GanttChartRoot
          border
          title={wlt("matrix.assignee")}
          loaderTitle="members"
          blockIds={blockIds}
          blockUpdateHandler={noopBlockUpdateHandler}
          blockToRender={(data: TWorkloadTimelineBlockData) => (
            <WorkloadTimelineChartBlock data={data} granularity={granularity} workspaceSlug={workspaceSlug} />
          )}
          sidebarToRender={() => (
            <WorkloadTimelineSidebarRow
              blockIds={blockIds}
              collapsed={collapsed}
              onToggleCollapse={toggleCollapse}
              focusWeek={focusWeek}
              renderTaskLabel={(taskData) => (
                <WorkloadTaskLink
                  task={taskData.task}
                  workspaceSlug={workspaceSlug}
                  className="flex min-w-0 flex-1 items-center gap-1.5 truncate text-primary hover:underline"
                >
                  <span className="flex-shrink-0 text-11 font-medium text-tertiary tabular-nums">
                    {taskData.task.identifier}
                  </span>
                  <span className="truncate text-13">{taskData.task.name}</span>
                </WorkloadTaskLink>
              )}
            />
          )}
          enableBlockLeftResize={false}
          enableBlockRightResize={false}
          enableBlockMove={false}
          enableReorder={false}
          enableAddBlock={false}
          enableSelection={false}
          enableDependency={false}
          showToday
        />
      </div>
    </TimeLineTypeContext.Provider>
  );
});
