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

/**
 * The period the swimlane badge reports on, as an inclusive date range.
 *
 * It follows the chart: whatever week / month / quarter sits under the centre
 * of the viewport is what the badge measures. That keeps the number answering
 * the question the reader is actually looking at — scroll to March and the
 * badge is about March — instead of being pinned to today's week while the
 * columns show something else entirely.
 *
 * The period is one step COARSER than the bucketing, which is what makes the
 * badge a summary rather than a restatement of a single cell:
 *
 *   gantt week    -> day buckets    -> badge covers the centred WEEK
 *   gantt month   -> week buckets   -> badge covers the centred MONTH
 *   gantt quarter -> month buckets  -> badge covers the centred QUARTER
 */
export type TFocusPeriod = { from: string; to: string; label: string };

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function iso(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The [start, end] of the week containing `date`, honouring the workspace's week start. */
function weekRange(date: Date, weekStartDay: number): { from: string; to: string } {
  const start = new Date(date);
  start.setDate(start.getDate() - ((start.getDay() - weekStartDay + 7) % 7));
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return { from: iso(start), to: iso(end) };
}

function monthRange(date: Date): { from: string; to: string } {
  const y = date.getFullYear();
  const m = date.getMonth();
  return { from: `${y}-${pad(m + 1)}-01`, to: iso(new Date(y, m + 1, 0)) };
}

function quarterRange(date: Date): { from: string; to: string } {
  const y = date.getFullYear();
  const q = Math.floor(date.getMonth() / 3);
  return { from: `${y}-${pad(q * 3 + 1)}-01`, to: iso(new Date(y, q * 3 + 3, 0)) };
}

/**
 * Resolve the badge's period from the date at the centre of the viewport.
 * `granularity` is the CURRENT bucketing, which the caller derives from the
 * chart's zoom — see the type docstring for the pairing.
 */
export function focusPeriodFor(
  centreDate: Date,
  granularity: TWorkloadGranularity,
  weekStartDay: number
): TFocusPeriod {
  if (granularity === "day") {
    const r = weekRange(centreDate, weekStartDay);
    return { ...r, label: `Week of ${r.from}` };
  }
  if (granularity === "week") {
    const r = monthRange(centreDate);
    return {
      ...r,
      label: centreDate.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
    };
  }
  const r = quarterRange(centreDate);
  return { ...r, label: `Q${Math.floor(centreDate.getMonth() / 3) + 1} ${centreDate.getFullYear()}` };
}

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

    // Footer closes the swimlane. Emitted only when expanded (a collapsed
    // member is one line), and only when it has something to say — an empty
    // strip would just be 44px of blank chart.
    const hasFooterContent =
      row.tasks.some((t) => !t.target_date) || row.tasks.some((t) => t.overdue) || row.tasks_truncated;
    if (hasFooterContent) {
      const footerId = `wl-footer:${key}`;
      blockIds.push(footerId);
      dataById[footerId] = {
        kind: "footer",
        id: footerId,
        name: row.assignee_name,
        assigneeId: row.assignee_id,
        row,
        sort_order: order++,
        start_date: headerStart,
        target_date: headerEnd,
      };
    }
  }

  return { blockIds, dataById };
}
