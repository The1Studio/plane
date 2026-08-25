// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — pure builder from a
// `TWorkloadResponse` to the flat, ordered `blockIds` list + block-data map
// `GanttChartRoot` needs. Kept dependency-free of React/MobX so it's testable
// in isolation.

import { packTasksIntoLanes, periodDateRange, selectPlaceholderTasks } from "@plane/workload-ext";
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

    // Placeholders and dated work go through ONE packing pass.
    //
    // A placeholder occupies exactly one day — its anchor (`start_date ??
    // today`) — so there is no reason it should own a whole row. It did until
    // now, on the argument that undated bars "all sit on the same column and
    // cannot share one". Half true: two anchored on the SAME day do collide,
    // and the packer already keeps those apart because their spans overlap.
    // But one anchored at its own start date and one at today do not collide
    // at all, and neither does a dated bar three days later — each of those
    // was costing a row for nothing. Observed on namph's swimlane: CRAZYLAB-134
    // anchored on the 23rd sat alone while LIHUHU-115 and ONDI-5, both at
    // today, took the two rows under it.
    //
    // Selection still runs first and still caps each group at three, so the
    // number of placeholder bars is unchanged — only where they land is. The
    // cap has to be applied BEFORE packing: handing `packTasksIntoLanes` a
    // row's whole undated backlog would lane all twenty of them.
    const placeholders = selectPlaceholderTasks(row.tasks, todayISO, packSpan);

    // Compact: several non-overlapping tasks share one row. A member with 49
    // scheduled tasks was 49 rows tall; packed, it is as many rows as they have
    // genuinely concurrent work, which is usually a handful.
    //
    // ESTIMATED AND UNESTIMATED TOGETHER. They used to be split into two bands
    // so that no row would interleave dashed and solid bars — a tidiness
    // argument that cost a row every time either group had a free slot the
    // other could have filled. The interleaving it prevented is not actually
    // confusing: dashed-versus-solid and `?`-versus-`12h` already distinguish
    // the two at a glance, on a row or across one.
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
    //
    // The window test is applied to DATED tasks only; a placeholder was
    // already filtered by ANCHOR inside `selectPlaceholderTasks`, and testing
    // it again here on a null `target_date` would drop every one of them.
    const dated = row.tasks.filter(
      (t) => t.target_date && (t.start_date ?? t.target_date) <= packSpan.to && t.target_date >= packSpan.from
    );
    const lanes = packTasksIntoLanes(
      [...placeholders.unscheduled.shown, ...placeholders.unestimated.shown, ...dated],
      todayISO
    );
    // A member with nothing to draw in this window — no tasks at all, or none
    // whose span or anchor lands inside `packSpan` — packs into zero lanes.
    // Without this fallback that member would get no lane block at all, and
    // therefore no click-to-create surface (I1): render one empty lane so the
    // row still exists to click on.
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
        // A lane can now hold a task with no `target_date`, which the renderer
        // has to place at `start_date ?? todayISO`. Carried on the block rather
        // than resolved here so the bar and its drag handler agree on one date,
        // and so this builder stays pure of the clock.
        todayISO,
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
    // Both numbers are OVERFLOWS, and of disjoint groups. Each reports only
    // what its own placeholder cap could not draw, so neither restates bars
    // already on screen a few rows up and the two can never count the same
    // item twice.
    //
    // `unestimatedHidden` was the swimlane TOTAL until 2026-08-25. Two things
    // were wrong with that: it overlapped the unscheduled number beside it,
    // and it counted bars the reader could already see. A dated unestimated
    // task is never in it — those are packed into the lanes uncapped, so the
    // only unestimated work that can be hidden is undated work past the cap.
    const unestimatedHidden = placeholders.unestimated.hiddenCount;
    // The UNSCHEDULED group's overflow ALONE. It briefly summed both groups,
    // which put every hidden unestimated item into this number AND into the
    // one beside it — namph's strip read "Unscheduled (22 more) Unestimated
    // (17)" with 14 items counted in both. `Unscheduled` is the estimated-
    // undated set, matching `meta.issues_unscheduled` server-side; an item
    // that is both undated and unestimated belongs to the other group.
    //
    // The bug was invisible on the swimlane it shipped against: XuanCuong has
    // exactly one unestimated item and it fits, so the second term was 0 and
    // the sum happened to be right. A term that is usually zero is exactly the
    // kind that survives a spot check.
    const unscheduledHidden = placeholders.unscheduled.hiddenCount;
    const hasFooterContent =
      unscheduledHidden > 0 || unestimatedHidden > 0 || row.tasks.some((t) => t.overdue) || row.tasks_truncated;
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
        unestimatedHidden,
        sort_order: order++,
        start_date: headerStart,
        target_date: headerEnd,
      };
    }
  }

  return { blockIds, dataById };
}
