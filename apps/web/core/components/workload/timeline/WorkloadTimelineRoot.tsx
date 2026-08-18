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
import { autorun } from "mobx";
import { observer } from "mobx-react";
import { GANTT_TIMELINE_TYPE } from "@plane/types";
import type { IBlockUpdateData } from "@plane/types";
import type { IWorkloadStore } from "@plane/workload-ext";
import { wlt } from "@plane/workload-ext";
import { TimeLineTypeContext } from "@/components/gantt-chart/contexts";
import { GanttChartRoot } from "@/components/gantt-chart/root";
import { useTimeLineChart } from "@/hooks/use-timeline-chart";
import { BaseTimeLineStore } from "@/plane-web/store/timeline/base-timeline.store";
import { buildWorkloadBlocks } from "./blocks";
import { WorkloadTimelineChartBlock } from "./WorkloadTimelineChartBlock";
import { WorkloadTimelineSidebarRow } from "./WorkloadTimelineSidebarRow";
import type { TWorkloadTimelineBlockData } from "./types";

type Props = {
  store: IWorkloadStore;
};

const noopBlockUpdateHandler = (_block: unknown, _payload: IBlockUpdateData) => {
  // Drag/resize/reorder are all disabled (D14, out of scope) — GanttChartRoot
  // still requires a handler prop, but it is never invoked.
};

export const WorkloadTimelineRoot = observer(function WorkloadTimelineRoot({ store }: Props) {
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
    return buildWorkloadBlocks(store.workloadData, store.granularity, collapsed);
  }, [store.workloadData, store.granularity, collapsed]);

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

  if (store.isLoading) {
    return <div className="py-8 text-center text-13 text-tertiary">{wlt("common.loading")}</div>;
  }
  if (store.error) {
    return <div className="py-4 text-13 text-danger-primary">{store.error}</div>;
  }
  if (!store.workloadData || store.workloadData.rows.length === 0) {
    return <div className="py-8 text-center text-13 text-placeholder">{wlt("timeline.no_workload_data")}</div>;
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
            <WorkloadTimelineChartBlock data={data} granularity={granularity} />
          )}
          sidebarToRender={() => (
            <WorkloadTimelineSidebarRow blockIds={blockIds} collapsed={collapsed} onToggleCollapse={toggleCollapse} />
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
