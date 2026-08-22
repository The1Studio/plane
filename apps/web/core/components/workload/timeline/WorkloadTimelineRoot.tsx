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
import { wlt } from "@plane/workload-ext";
import { TimeLineTypeContext } from "@/components/gantt-chart/contexts";
import { GanttChartRoot } from "@/components/gantt-chart/root";
import { useTimeLineChart } from "@/hooks/use-timeline-chart";
import { BaseTimeLineStore } from "@/plane-web/store/timeline/base-timeline.store";
import { SIDEBAR_WIDTH } from "@/components/gantt-chart/constants";
import { getDateFromPositionOnGantt } from "@/components/gantt-chart/views";
import { useWorkSettings } from "@/hooks/store/use-work-settings";
import { buildWorkloadBlocks, focusPeriodFor } from "./blocks";
import type { TFocusPeriod } from "./blocks";
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

function addDays(d: Date, days: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + days);
  return out;
}

function toDateStr(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

const noopBlockUpdateHandler = (_block: unknown, _payload: IBlockUpdateData) => {
  // Drag/resize/reorder are all disabled (D14, out of scope) — GanttChartRoot
  // still requires a handler prop, but it is never invoked.
};

export const WorkloadTimelineRoot = observer(function WorkloadTimelineRoot({ store, workspaceSlug }: Props) {
  // Only the keys the reader has toggled BY HAND in the current zoom. Every
  // other key falls through to `defaultCollapsed` below — see `isCollapsed`.
  const [collapseOverrides, setCollapseOverrides] = useState<Record<string, boolean>>({});
  // `useTimeLineChart` is typed to return the `IBaseTimelineStore` interface
  // (shared by every timeline type), but `getTimelineStore` (ce/hooks/use-timeline-chart.ts)
  // resolves GANTT_TIMELINE_TYPE.WORKLOAD to a genuine `BaseTimeLineStore` instance
  // (ce/store/timeline/index.ts) — cast to reach `updateBlocks`, its one public
  // method the interface doesn't carry (only the ISSUE/MODULE stores' own
  // internal autorun calls it today).
  const timelineStore = useTimeLineChart(GANTT_TIMELINE_TYPE.WORKLOAD) as BaseTimeLineStore;

  // ── Collapse: a per-zoom default, overridden per row ───────────────────────
  //
  // Week zoom opens expanded; Month and Quarter open with every swimlane
  // collapsed to its header, so the board reads as one line of capacity per
  // member. `currentView` is a MobX observable and this component is an
  // `observer`, so reading it here re-renders on zoom change with no reaction
  // of its own — the `reaction` further down does a different job (it pushes
  // the zoom into the store's BUCKETING) and is not a substitute for this.
  const defaultCollapsed = timelineStore.currentView !== "week";

  // Why a per-key default instead of materialising a collapsed Set when the
  // zoom changes: rows load ASYNCHRONOUSLY, from the viewport-driven
  // `ensureRange` calls below. A set snapshotted at zoom-change time knows only
  // the rows loaded by then, so any member the reader later panned into view
  // would render EXPANDED in Month zoom — the default silently applying to some
  // rows and not others, with nothing in the UI to explain the difference.
  const isCollapsed = useCallback(
    (key: string) => collapseOverrides[key] ?? defaultCollapsed,
    [collapseOverrides, defaultCollapsed]
  );

  // A zoom change drops manual toggles so the new zoom's default wins on
  // arrival. Keyed on `defaultCollapsed`, NOT on `currentView`: Month and
  // Quarter share a default, so switching between those two changes nothing
  // about what the reader asked for and their toggles are left alone. Only
  // Week↔Month and Week↔Quarter flip the boolean, and only those reset.
  useEffect(() => {
    // Returning `prev` unchanged when there is nothing to clear lets React bail
    // out of the re-render; a fresh `{}` would not compare equal and would cost
    // an extra render pass on every mount.
    setCollapseOverrides((prev) => (Object.keys(prev).length === 0 ? prev : {}));
  }, [defaultCollapsed]);

  const toggleCollapse = useCallback(
    (key: string) => {
      setCollapseOverrides((prev) => ({ ...prev, [key]: !(prev[key] ?? defaultCollapsed) }));
    },
    [defaultCollapsed]
  );

  const { blockIds, dataById } = useMemo(() => {
    if (!store.workloadData)
      return { blockIds: [] as string[], dataById: {} as Record<string, TWorkloadTimelineBlockData> };
    return buildWorkloadBlocks(store.workloadData, store.granularity, isCollapsed);
  }, [store.workloadData, store.granularity, isCollapsed]);

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

  // ── Viewport-driven loading ────────────────────────────────────────────────
  //
  // There is no date-range picker: what the reader has scrolled to IS the
  // range. `#gantt-container` is core's scroll element (it carries a
  // DO-NOT-REMOVE id) and `getDateFromPositionOnGantt` turns a pixel offset in
  // its content into a date, so the visible span and its centre both fall out
  // of `scrollLeft` + `clientWidth`.
  //
  // Attaching our own listener instead of reaching into `ChartViewRoot`'s
  // `onScroll` keeps this pure composition: core is untouched and its own
  // handler, which paginates the axis, still runs alongside this one.
  const { workSettings } = useWorkSettings(workspaceSlug);
  const weekStartDay = workSettings.week_start_day;
  const [focus, setFocus] = useState<TFocusPeriod | null>(null);
  // The last span asked for, so a zoom or filter change can reload the same
  // view without waiting for the reader to scroll.
  const lastRangeRef = useRef<{ from: string; to: string } | null>(null);

  const syncViewport = useCallback(() => {
    const el = document.getElementById("gantt-container");
    const chart = timelineStore.currentViewData;
    if (!el || !chart) return;

    // The sidebar is sticky INSIDE the scroll container, overlaying the first
    // SIDEBAR_WIDTH pixels — so the leftmost genuinely visible chart pixel sits
    // that far past `scrollLeft`, not at it.
    const leftPx = el.scrollLeft + SIDEBAR_WIDTH;
    const rightPx = el.scrollLeft + el.clientWidth;
    const from = getDateFromPositionOnGantt(leftPx, chart);
    const to = getDateFromPositionOnGantt(rightPx, chart);
    const centre = getDateFromPositionOnGantt((leftPx + rightPx) / 2, chart);
    if (!from || !to || !centre) return;

    setFocus(focusPeriodFor(centre, store.granularity, weekStartDay));

    // Load a viewport's width either side too, so ordinary panning lands on
    // data already held rather than on empty columns that fill in a moment
    // later. `ensureRange` requests only what is missing, so the padding costs
    // nothing once it has been fetched.
    const spanDays = Math.max(1, Math.round((to.getTime() - from.getTime()) / 86_400_000));
    const padded = { from: toDateStr(addDays(from, -spanDays)), to: toDateStr(addDays(to, spanDays)) };
    lastRangeRef.current = padded;
    void store.ensureRange(workspaceSlug, padded, weekStartDay);
  }, [timelineStore, store, workspaceSlug, weekStartDay]);

  // Scroll settle. Panning fires continuously, so this is debounced — without
  // it a single drag would queue a request per frame.
  useEffect(() => {
    const el = document.getElementById("gantt-container");
    if (!el) return;
    let timer: ReturnType<typeof setTimeout>;
    const onScroll = () => {
      clearTimeout(timer);
      timer = setTimeout(syncViewport, 250);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    // Once on mount as well: the first paint has a viewport but no scroll event.
    syncViewport();
    return () => {
      clearTimeout(timer);
      el.removeEventListener("scroll", onScroll);
    };
  }, [syncViewport]);

  // A zoom or filter change empties the cache but does not scroll, so nothing
  // above would fire. Re-ask for the span already on screen.
  useEffect(() => {
    if (store.coverageVersion === 0) return;
    syncViewport();
  }, [store.coverageVersion, syncViewport]);

  // The chart's zoom is the granularity control. Changing it drops the range
  // cache (the store's setter does that), and the viewport sync below reloads
  // whatever is on screen at the new bucketing. `reaction`, not `autorun`, so
  // it never fires on the initial read — the two already agree at construction.
  useEffect(
    () =>
      reaction(
        () => timelineStore.currentView,
        (view: TGanttViews) => {
          const next = VIEW_TO_GRANULARITY[view];
          if (next) store.setGranularity(next);
        }
      ),
    [timelineStore, store]
  );

  const granularity = store.granularity;

  // The chart is ALWAYS rendered. Every state below is an overlay on top of it,
  // never a replacement, for two reasons:
  //
  //  - Returning early on "no data yet" DEADLOCKS the page. Loading is driven
  //    by the viewport of `#gantt-container`, so a first paint that renders a
  //    placeholder instead of the chart never mounts that element, never
  //    measures a viewport, and therefore never fetches the data that would
  //    have replaced the placeholder.
  //  - Returning early on `isLoading` would blank the whole board on every pan,
  //    since panning is now what triggers loading.
  const hasRows = (store.workloadData?.rows.length ?? 0) > 0;
  const counted = store.workloadData?.meta?.issues_counted ?? 0;

  return (
    <TimeLineTypeContext.Provider value={GANTT_TIMELINE_TYPE.WORKLOAD}>
      {/* `isolate` confines every z-index inside the chart to this container.
          Without it the gantt sidebar (`sticky z-10`, sidebar/root.tsx) ties with
          the toolbar dropdowns' panels (`fixed z-10`, e.g. dropdowns/project/base.tsx)
          and wins on DOM order, because the timeline is rendered after the
          toolbar — so an open Projects/Members dropdown was painted UNDER the
          board. Isolating here fixes it without editing either core file.
          Full-screen mode is unaffected: it `createPortal`s out to
          #full-screen-portal, which is not inside this container. */}
      <div className="relative isolate h-[70vh] w-full">
        {!hasRows && (
          // "No rows" and "no data" are NOT the same thing, and conflating them
          // is what let a real bug hide: a member with 71 estimated tasks
          // rendered an empty board because every target date fell just outside
          // the window. `issues_counted` is counted BEFORE date clipping, so it
          // tells the two apart.
          <div className="pointer-events-none absolute inset-0 z-[5] flex items-start justify-center pt-24">
            <span className="text-13 text-placeholder">
              {store.isLoading
                ? wlt("common.loading")
                : counted > 0
                  ? wlt("timeline.no_data_in_range", { count: counted })
                  : wlt("timeline.no_workload_data")}
            </span>
          </div>
        )}
        {store.error && (
          // Shown alongside the board, not instead of it: one failed span must
          // not discard the spans that loaded fine.
          <div className="absolute top-2 right-2 z-[6] rounded-md bg-danger-subtle px-2 py-1 text-11 text-danger-primary">
            {store.error}
          </div>
        )}
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
              isCollapsed={isCollapsed}
              onToggleCollapse={toggleCollapse}
              focus={focus}
              granularity={granularity}
              workSettings={workSettings}
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
