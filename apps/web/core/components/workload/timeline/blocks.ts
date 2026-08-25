// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — pure builder from a
// `TWorkloadResponse` to the flat, ordered `blockIds` list + block-data map
// `GanttChartRoot` needs. Kept dependency-free of React/MobX so it's testable
// in isolation.

import {
  packTasksIntoLanes,
  periodDateRange,
  selectPlaceholderTasks,
  splitByEstimate,
  unscheduledAnchorDate,
} from "@plane/workload-ext";
import type { TWorkloadGranularity, TWorkloadResponse, TWorkloadTask } from "@plane/workload-ext";
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
 * header, task, ...]`, in `data.rows` order (already sorted server-side —
 * `Unassigned` first, then ascending by `assignee_name`, case-insensitively;
 * see service.py `rows.sort`). Collapsing a member
 * removes its task blockIds but KEEPS its header — this is what satisfies the
 * "collapsing hides bars but keeps the axis aligned" success criterion,
 * since every OTHER row's block is untouched and BlockRow stacks purely by
 * list order.
 *
 * `isCollapsed` is a PREDICATE, not a set of collapsed keys, and the difference
 * is load-bearing. Collapse now has a per-zoom DEFAULT (expanded at Week,
 * collapsed at Month/Quarter) that manual toggles override, and rows arrive
 * asynchronously as the reader pans — so a key this builder has never seen
 * before must still resolve to the current default. A set can only answer for
 * the rows that existed when it was built; a predicate answers for every key,
 * including one that loads a second from now.
 */
export function buildWorkloadBlocks(
  data: TWorkloadResponse,
  granularity: TWorkloadGranularity,
  isCollapsed: (assigneeKey: string) => boolean,
  /**
   * Today as `YYYY-MM-DD`, in the reader's own timezone. Passed in rather than
   * read from `new Date()` here for the same reason `granularity` is: a builder
   * that reads the clock cannot be tested, and this one is pure by design.
   */
  todayISO: string,
  /**
   * The week-aligned span lanes and placeholders are computed over — see
   * `weekAlignedWindow`. `null` before the first viewport sync (and in any
   * caller that has no viewport), which falls back to the response's own
   * window: the pre-pack-window behaviour, and never narrower than what the
   * data covers, so nothing can disappear on first paint.
   */
  packWindow: { from: string; to: string } | null
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
  // Falls back to the response's own window, which is never narrower than the
  // data — so a caller with no viewport yet gets exactly the pre-pack-window
  // behaviour rather than an empty board.
  const packSpan = packWindow ?? { from: data.date_from, to: data.date_to };

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

    if (isCollapsed(key)) continue;

    // Placeholder bars first, above the packed lanes. Each gets its OWN row:
    // undated bars all sit on the same column, so unlike dated tasks they
    // cannot share one, and once these bars are draggable a bar's x-position
    // is a claim about a date — two side by side would both claim a day only
    // the leftmost actually occupies.
    //
    // Two groups with SEPARATE budgets, unscheduled above unestimated. One
    // shared budget let a single unestimated item take the top slot (
    // `_task_sort_key` sorts unestimated first) and push a member's real
    // unscheduled backlog further behind a counter.
    const placeholders = selectPlaceholderTasks(row.tasks, todayISO, packSpan);
    const emitPlaceholders = (group: TWorkloadTask[], prefix: string) =>
      group.forEach((task, index) => {
        const id = `${prefix}:${key}:${index}`;
        blockIds.push(id);
        dataById[id] = {
          kind: "unscheduled",
          id,
          name: task.name,
          assigneeId: row.assignee_id,
          task,
          anchorDate: unscheduledAnchorDate(task, todayISO),
          sort_order: order++,
          // Whole-window span, exactly as the header and footer use — the bar
          // is placed inside this box by absolute date.
          start_date: headerStart,
          target_date: headerEnd,
        };
      });
    emitPlaceholders(placeholders.unscheduled.shown, "wl-unsched");
    emitPlaceholders(placeholders.unestimated.shown, "wl-unest-ph");

    // Compact: several non-overlapping tasks share one row. A member with 49
    // scheduled tasks was 49 rows tall; packed, it is as many rows as they have
    // genuinely concurrent work, which is usually a handful.
    //
    // ESTIMATED AND UNESTIMATED TOGETHER, in ONE packing pass. They used to be
    // split into two bands so that no row would interleave dashed and solid
    // bars — a tidiness argument that cost a row every time either group had a
    // free slot the other could have filled. Measured on the DEVOPS board it
    // was 6 wasted rows on one swimlane, and the interleaving it prevented is
    // not actually confusing: dashed-versus-solid and `?`-versus-`12h` already
    // distinguish the two at a glance, on a row or across one.
    //
    // Unestimated items are packed like any other dated bars because they HAVE
    // dates; only the estimate is missing. An UNDATED one is not in this set —
    // it has no `target_date`, so `packTasksIntoLanes` drops it and the
    // placeholder block above already drew it.
    //
    // Packed over `packSpan`, NOT over every task the store holds. Lane count
    // is peak concurrency, so packing the whole fetched set makes the swimlane
    // as tall as its busiest day anywhere in that set — and the store
    // accumulates tasks as the reader pans, so that height only grows, leaving
    // rows whose bars are all off-screen. `packSpan` is snapped outward to
    // whole COLUMNS of the current zoom (day at Week, week at Month, month at
    // Quarter — see `columnAlignedWindow`), so it always covers the visible
    // columns (plus a day of slack for the caller's pixel rounding) and
    // changes only when the reader scrolls a whole column past.
    // Not weeks: a week-aligned window re-admits the off-screen work it was
    // meant to exclude whenever the viewport starts mid-week, which is the
    // normal case.
    const lanes = packTasksIntoLanes(
      row.tasks.filter(
        (t) => !t.target_date || ((t.start_date ?? t.target_date) <= packSpan.to && t.target_date >= packSpan.from)
      )
    );
    // A member with no scheduled tasks — zero tasks at all, or every task
    // unscheduled (no `target_date`, so `packTasksIntoLanes` places none of
    // them) — packs into zero lanes. Without this fallback that member would
    // get no lane block at all, and therefore no click-to-create surface
    // (I1): render one empty lane so the row still exists to click on.
    const lanesToRender = lanes.length > 0 ? lanes : [[]];
    lanesToRender.forEach((laneTasks, laneIndex) => {
      const laneId = `wl-lane:${key}:${laneIndex}`;
      blockIds.push(laneId);
      dataById[laneId] = {
        kind: "lane",
        id: laneId,
        name: laneTasks[0]?.name ?? row.assignee_name,
        assigneeId: row.assignee_id,
        tasks: laneTasks,
        sort_order: order++,
        // The lane's box spans the WHOLE response window (same as the header
        // block above), not the bars' own bounding range — this is what gives
        // `WorkloadCreateOverlay` a click-to-create surface across the FULL
        // swimlane row (I1), not just the gaps between existing bars, and
        // what lets a lane with zero tasks still render a create-surface at
        // all. Bars are positioned inside this box by ABSOLUTE date, so
        // widening the box changes nothing about where a bar paints.
        start_date: headerStart,
        target_date: headerEnd,
      };
    });

    // Footer closes the swimlane. Emitted only when expanded (a collapsed
    // member is one line), and only when it has something to say — an empty
    // strip would just be 44px of blank chart.
    // Only the OVERFLOW counts now. The unscheduled tasks the cap did draw are
    // on screen a few rows up; repeating them in a number invites the reader to
    // add the two together. When everything fits, this half of the strip has
    // nothing to say and disappears.
    // `unestimatedCount` is the TOTAL, not an overflow like
    // `unscheduled.hiddenCount`: unestimated bars are not capped as a group,
    // so every one of them is already on screen. It is still worth a number —
    // "how much of this swimlane is unestimated" is not answerable by counting
    // dashes across a scrolled chart, and less so now that they are mixed into
    // the same lanes as estimated work rather than sitting in their own band.
    //
    // Counted from the row's OWN tasks rather than from a packing result: the
    // undated ones are drawn by the placeholder block above and never reach
    // `lanes`, but they are still unestimated work this swimlane owes an
    // estimate for.
    const unestimatedCount = splitByEstimate(row.tasks).unestimated.length;
    const unscheduledHidden = placeholders.unscheduled.hiddenCount + placeholders.unestimated.hiddenCount;
    const hasFooterContent =
      unscheduledHidden > 0 || unestimatedCount > 0 || row.tasks.some((t) => t.overdue) || row.tasks_truncated;
    if (hasFooterContent) {
      const footerId = `wl-footer:${key}`;
      blockIds.push(footerId);
      dataById[footerId] = {
        kind: "footer",
        id: footerId,
        name: row.assignee_name,
        assigneeId: row.assignee_id,
        row,
        unscheduledHidden,
        unestimatedCount,
        sort_order: order++,
        start_date: headerStart,
        target_date: headerEnd,
      };
    }
  }

  return { blockIds, dataById };
}
