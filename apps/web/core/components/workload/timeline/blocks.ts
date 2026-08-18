// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — pure builder from a
// `TWorkloadResponse` to the flat, ordered `blockIds` list + block-data map
// `GanttChartRoot` needs. Kept dependency-free of React/MobX so it's testable
// in isolation.

import { periodDateRange } from "@plane/workload-ext";
import type { TWorkloadGranularity, TWorkloadResponse } from "@plane/workload-ext";
import { assigneeKey } from "./types";
import type { TWorkloadTimelineBlockData } from "./types";

export type TWorkloadBlocksResult = {
  blockIds: string[];
  dataById: Record<string, TWorkloadTimelineBlockData>;
};

/**
 * Builds the flat blockIds run for every swimlane: `[header, task, task, ...,
 * header, task, ...]`, in `data.rows` order (already sorted server-side by
 * `-total, assignee_name` — service.py `rows.sort`). Collapsing a member
 * removes its task blockIds but KEEPS its header — this is what satisfies the
 * "collapsing hides bars but keeps the axis aligned" success criterion,
 * since every OTHER row's block is untouched and BlockRow stacks purely by
 * list order.
 */
export function buildWorkloadBlocks(
  data: TWorkloadResponse,
  granularity: TWorkloadGranularity,
  collapsedAssigneeKeys: ReadonlySet<string>
): TWorkloadBlocksResult {
  const blockIds: string[] = [];
  const dataById: Record<string, TWorkloadTimelineBlockData> = {};

  const { periods } = data;
  const firstPeriod = periods[0];
  const lastPeriod = periods[periods.length - 1];
  // The header's span is the WHOLE response window, not a single period —
  // this is what makes it wide enough to host every period's heat cell.
  // Falls back to the request window when a workspace has zero periods
  // (every task unscheduled, or truly empty) so the header still gets a
  // valid, non-empty date range to position itself with.
  const headerStart = firstPeriod ? periodDateRange(firstPeriod, granularity).start : data.date_from;
  const headerEnd = lastPeriod ? periodDateRange(lastPeriod, granularity).end : data.date_to;

  let order = 0;
  for (const row of data.rows) {
    const key = assigneeKey(row.assignee_id);
    const headerId = `wl-header:${key}`;
    blockIds.push(headerId);
    dataById[headerId] = {
      kind: "header",
      id: headerId,
      name: row.assignee_name,
      assigneeId: row.assignee_id,
      row,
      periods,
      sort_order: order++,
      start_date: headerStart,
      target_date: headerEnd,
    };

    if (collapsedAssigneeKeys.has(key)) continue;

    for (const task of row.tasks) {
      // A task with no target_date is "Unscheduled" (mirrors service.py's own
      // routing: `target is None` always lands in the Unscheduled bucket).
      // The timeline has no window to plot it in — it's surfaced via the
      // header row's "Unscheduled (N)" affordance instead, never a bar.
      if (!task.target_date) continue;
      const taskId = `wl-task:${task.id}`;
      blockIds.push(taskId);
      dataById[taskId] = {
        kind: "task",
        id: taskId,
        name: task.name,
        assigneeId: row.assignee_id,
        task,
        sort_order: order++,
        start_date: task.start_date ?? undefined,
        target_date: task.target_date,
      };
    }
  }

  return { blockIds, dataById };
}
