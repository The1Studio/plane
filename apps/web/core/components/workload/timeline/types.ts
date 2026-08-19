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

/** One task bar. Only tasks with a non-null `target_date` become a block —
 * a task with no target is "Unscheduled" and is surfaced via the header
 * row's affordance instead (see `blocks.ts`). */
export type TWorkloadTaskBlockData = {
  kind: "task";
  id: string;
  name: string;
  assigneeId: string | null;
  task: TWorkloadTask;
  sort_order: number;
  start_date: string | undefined;
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
  sort_order: number;
  start_date: string;
  target_date: string;
};

export type TWorkloadTimelineBlockData = TWorkloadHeaderBlockData | TWorkloadTaskBlockData | TWorkloadFooterBlockData;

/**
 * Whether this row is over its WEEKLY capacity in any week of the response.
 *
 * The over-capacity signal is defined per week (the workspace configures a
 * weekly max), so a window total is the wrong test: a member at 60h one week
 * and idle the next is overloaded, and `total_over` — which compares the whole
 * window's hours against the whole window's capacity — reports them as fine.
 */
export function isOverWeeklyCapacity(row: TWorkloadRow): boolean {
  const capacity = row.weekly_capacity ?? 0;
  if (capacity <= 0) return false;
  return Object.values(row.weekly_buckets ?? {}).some((hours) => hours > capacity);
}
