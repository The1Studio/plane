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
import { assigneeKey, isOverWeeklyCapacity } from "./types";
import type { TWorkloadTimelineBlockData } from "./types";

/**
 * The week key whose figures the swimlane badge reports: the week containing
 * today, clamped into the response window.
 *
 * `weekly_buckets` is keyed by the containing week's FIRST DATE (never an ISO
 * week number — an arbitrary `week_start_day` has none), so this reproduces
 * `period_key(d, "week", week_start_day)` from the API's aggregation.py. That
 * duplication is unavoidable — the key has to be computed for a date the
 * response carries no bucket for — but it is confined to this one function.
 *
 * `weekStartDay` is a Plane `EStartOfTheWeek` value (SUNDAY=0..SATURDAY=6),
 * which is the opposite origin from JS `Date.getDay()`... except that
 * `getDay()` is ALSO Sunday=0, so the two already agree and no conversion is
 * needed here (unlike the Python side, where `date.weekday()` is Monday=0).
 */
export function weekKeyFor(dateStr: string, weekStartDay: number): string {
  const d = new Date(`${dateStr}T00:00:00`);
  const offset = (d.getDay() - weekStartDay + 7) % 7;
  d.setDate(d.getDate() - offset);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Local today as YYYY-MM-DD, matching the format the API speaks. */
function todayString(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/**
 * The workspace's week-start day, read back off the response's own weekly keys.
 *
 * Every `weekly_buckets` key IS a week's first date, produced server-side from
 * the workspace's `week_start_day`, so its weekday is that setting. Deriving it
 * here rather than calling `useWorkSettings` has two advantages: no second GET
 * on a page that already issues one (the hook fetches per instance — it is not
 * store-backed or deduped), and the value cannot DISAGREE with the bucketing it
 * is used to index, which is the only property that actually matters.
 *
 * Falls back to Monday (`DEFAULT_WEEK_START_DAY` in the API's constants.py)
 * when no row has any weekly bucket — in which case every badge reads `0h` and
 * the key is not used to find anything.
 */
function deriveWeekStartDay(data: TWorkloadResponse): number {
  for (const row of data.rows) {
    for (const key of Object.keys(row.weekly_buckets ?? {})) {
      const d = new Date(`${key}T00:00:00`);
      if (!Number.isNaN(d.getTime())) return d.getDay();
    }
  }
  return 1;
}

/**
 * Which week the badge reports on: today's, or the nearest edge of the window
 * when today falls outside it. Never returns a week the response has no column
 * for, so the badge is always about something the user can actually see.
 */
export function focusWeekKey(data: TWorkloadResponse): string {
  const weekStartDay = deriveWeekStartDay(data);
  const today = todayString();
  if (today < data.date_from) return weekKeyFor(data.date_from, weekStartDay);
  if (today > data.date_to) return weekKeyFor(data.date_to, weekStartDay);
  return weekKeyFor(today, weekStartDay);
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
  collapsedAssigneeKeys: ReadonlySet<string>,
  showOverCapacityOnly: boolean = false
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

  // The over-capacity switch hides whole swimlanes (phase-8.md "the
  // over-capacity filter now hides whole swimlanes rather than table rows").
  // It had been WIRED NOWHERE since the aggregate matrix was deleted: the
  // store field was written by the toolbar and read by no renderer, so the
  // control silently did nothing. The test is weekly, not window-total — see
  // `isOverWeeklyCapacity`.
  const rows = showOverCapacityOnly ? data.rows.filter(isOverWeeklyCapacity) : data.rows;

  let order = 0;
  for (const row of rows) {
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
