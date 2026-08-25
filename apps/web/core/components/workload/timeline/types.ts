// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — internal block-data shapes
// for the workload timeline. Composed on top of core's gantt-chart primitives
// (`GanttChartRoot`/`ChartViewRoot`), which render a flat, ordered `blockIds`
// list with no group/swimlane seam of their own (plan.md's "Prior art" table).
// A "swimlane" here is therefore represented as an ordered RUN of blocks: one
// `header` block (the capacity heat row + avatar/badge sidebar cell) followed
// by that assignee's `task` blocks — see `blocks.ts`.

import type { TWorkloadRow, TWorkloadTask } from "@plane/workload-ext";

/** Sentinel assignee key for the "Unassigned" swimlane (row.assignee_id is `null`). */
export const UNASSIGNED_KEY = "unassigned";

/** Stable string key for an assignee id, collapsing `null` to `UNASSIGNED_KEY`. */
export function assigneeKey(assigneeId: string | null): string {
  return assigneeId ?? UNASSIGNED_KEY;
}

/**
 * The swimlane's header row: avatar + name + used/capacity badge + collapse
 * chevron + Unscheduled/Overdue affordances (sidebar), and the per-period
 * capacity heat cells (chart body).
 *
 * `start_date`/`target_date` span the WHOLE `periods[]` range (not the
 * chart's own scroll viewport) — see `blocks.ts` for why this keeps the
 * block's position stable across pan/zoom instead of needing to track the
 * chart's currently-rendered window.
 */
export type TWorkloadHeaderBlockData = {
  kind: "header";
  id: string;
  name: string;
  assigneeId: string | null;
  row: TWorkloadRow;
  /** Same `periods` array as the API response — one heat cell per entry. */
  periods: string[];
  sort_order: number;
  start_date: string;
  target_date: string;
};

/**
 * One LANE of task bars — a set of tasks whose date ranges do not overlap, so
 * they can share a single row without colliding. May be EMPTY (`tasks: []`)
 * for a member with no scheduled tasks — see `blocks.ts`'s `lanesToRender`
 * fallback — so this still exists as a click-to-create surface even then.
 *
 * The chart lays out one row per blockId at a fixed `BLOCK_HEIGHT`, so packing
 * cannot be done by giving several blocks the same row. Instead a lane is ONE
 * block spanning the swimlane's WHOLE response window (same range as its
 * header), not just its own tasks' bounding range — the bars are positioned
 * inside that box by absolute date, the same technique the header row already
 * uses to place per-period heat cells (see WorkloadTimelineChartBlock). This
 * is also what gives `WorkloadCreateOverlay` a click-to-create surface across
 * the full row rather than only the gaps between existing bars (I1).
 *
 * Only tasks with a non-null `target_date` are placed. A task with no target is
 * "Unscheduled": the timeline has no window to plot it in, and it is surfaced
 * on the footer row instead, never as a bar.
 */
export type TWorkloadLaneBlockData = {
  kind: "lane";
  id: string;
  name: string;
  assigneeId: string | null;
  /**
   * Non-overlapping, ordered by start date.
   *
   * MAY include a task with no `target_date` — a placeholder, which occupies
   * the single day `start_date ?? todayISO` and is packed alongside dated work
   * rather than owning a row. The renderer resolves it against `todayISO`
   * below; nothing here may dereference `target_date` without checking.
   */
  tasks: TWorkloadTask[];
  /**
   * Today as `YYYY-MM-DD` in the reader's timezone, carried from
   * `buildWorkloadBlocks` so the bar and its drag handler resolve a
   * placeholder's anchor to the SAME day, and so neither reads the clock
   * mid-render.
   */
  todayISO: string;
  sort_order: number;
  start_date: string;
  target_date: string;
};

/**
 * The per-assignee footer strip: "Unscheduled (N)" / "Overdue (N)" / "showing
 * first N". Its own block kind rather than extra lines on the header, because
 * every row in the chart is laid out at core's shared `BLOCK_HEIGHT` (44px,
 * hardcoded in `gantt-chart/blocks/block-row.tsx`) — a taller header would
 * mean a core edit, whereas one more 44px block needs none.
 *
 * Spans the same dates as its swimlane's header so `BlockRow`'s
 * "drop blocks with no dates" guard keeps it; its chart-side render is empty.
 */
export type TWorkloadFooterBlockData = {
  kind: "footer";
  id: string;
  name: string;
  assigneeId: string | null;
  row: TWorkloadRow;
  /**
   * How many unscheduled tasks the lane cap hid — NOT the total.
   *
   * Passed down rather than recomputed from `row.tasks`, because the number
   * is a function of the cap the block builder applied. Recomputing it here
   * would restate that cap in a second place, and the two would drift the
   * first time it changed.
   */
  unscheduledHidden: number;
  /**
   * How many of this swimlane's tasks carry no estimate — the TOTAL, unlike
   * `unscheduledHidden` above.
   *
   * Unestimated bars are not capped as a group, so all of them are already on
   * screen and there is no hidden remainder to report. The number is still
   * worth showing: "how much of this swimlane is unestimated" is not something
   * a reader can answer by counting dashed bars across a scrolled chart.
   */
  unestimatedCount: number;
  sort_order: number;
  start_date: string;
  target_date: string;
};

export type TWorkloadTimelineBlockData = TWorkloadHeaderBlockData | TWorkloadLaneBlockData | TWorkloadFooterBlockData;
