/**
 * Range algebra + response merging for the timeline's incremental loading.
 *
 * The timeline has no date-range picker: the chart's viewport IS the range, and
 * panning fetches only the part that is not already loaded, merging it into
 * what is held. This module is the pure half of that — no MobX, no network.
 *
 * THE INVARIANT THAT MAKES MERGING SAFE: every fetched sub-range is snapped
 * OUTWARD to whole `granularity` periods (see `snapRangeToPeriods`). A period
 * key is therefore produced by exactly ONE fetch, so merging is a plain key
 * UNION and never an addition. That matters because the alternative — summing
 * partial buckets from overlapping windows — silently double-counts the moment
 * a range is fetched twice, and nothing on screen would say so.
 *
 * Dates are inclusive `YYYY-MM-DD` strings throughout. That format sorts
 * correctly under plain string comparison, so the range algebra needs no Date
 * objects except to step a day.
 */

import { periodDateRange, shiftDate } from "./dateRange";
import type { TWorkloadGranularity, TWorkloadResponse, TWorkloadRow, TWorkloadTask } from "./types";

export type TDateRange = { from: string; to: string };

// ── Period snapping ──────────────────────────────────────────────────────────

/**
 * The bucket key a date falls in — the client-side mirror of `period_key()` in
 * the API's `aggregation.py`. `weekStartDay` is a Plane `EStartOfTheWeek` value
 * (SUNDAY=0..SATURDAY=6); JS `Date.getDay()` shares that origin, so no
 * conversion is needed here (unlike Python, whose `weekday()` starts Monday).
 */
export function periodKeyFor(dateStr: string, granularity: TWorkloadGranularity, weekStartDay: number): string {
  if (granularity === "day") return dateStr;
  if (granularity === "month") return dateStr.slice(0, 7);
  const d = new Date(`${dateStr}T00:00:00`);
  const offset = (d.getDay() - weekStartDay + 7) % 7;
  d.setDate(d.getDate() - offset);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Widen a range to whole periods. This is what guarantees a period key belongs
 * to exactly one fetch, and therefore that `mergeWorkloadResponses` can union
 * rather than add.
 */
export function snapRangeToPeriods(
  range: TDateRange,
  granularity: TWorkloadGranularity,
  weekStartDay: number
): TDateRange {
  const first = periodDateRange(periodKeyFor(range.from, granularity, weekStartDay), granularity);
  const last = periodDateRange(periodKeyFor(range.to, granularity, weekStartDay), granularity);
  return { from: first.start, to: last.end };
}

// ── Range algebra ────────────────────────────────────────────────────────────

/** Sort, then fuse overlapping or day-adjacent ranges into the fewest spans. */
export function normalizeRanges(ranges: TDateRange[]): TDateRange[] {
  const sorted = ranges.filter((r) => r.from <= r.to).toSorted((a, b) => (a.from < b.from ? -1 : 1));
  const out: TDateRange[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    // Adjacent counts as overlapping: [Jan 1..Jan 5] and [Jan 6..Jan 9] are one
    // covered span, and leaving them separate would make the gap arithmetic
    // below ask for an empty range between them on every pan.
    if (last && r.from <= shiftDate(last.to, 1)) {
      if (r.to > last.to) last.to = r.to;
    } else {
      out.push({ ...r });
    }
  }
  return out;
}

/** The parts of `want` that `covered` does not already include. */
export function subtractRanges(want: TDateRange, covered: TDateRange[]): TDateRange[] {
  if (want.from > want.to) return [];
  const gaps: TDateRange[] = [];
  let cursor = want.from;
  for (const c of normalizeRanges(covered)) {
    if (c.to < cursor) continue; // entirely before the part still needed
    if (c.from > want.to) break; // entirely after
    if (c.from > cursor) gaps.push({ from: cursor, to: shiftDate(c.from, -1) });
    cursor = shiftDate(c.to, 1);
    if (cursor > want.to) return gaps;
  }
  if (cursor <= want.to) gaps.push({ from: cursor, to: want.to });
  return gaps;
}

// ── Response merging ─────────────────────────────────────────────────────────

const rowKey = (row: TWorkloadRow) => row.assignee_id ?? " unassigned";

function mergeRow(base: TWorkloadRow, add: TWorkloadRow): TWorkloadRow {
  // Plain unions — see this module's header for why no key can collide with a
  // DIFFERENT value, and therefore why nothing here adds.
  const buckets = { ...base.buckets, ...add.buckets };
  const month_buckets = { ...base.month_buckets, ...add.month_buckets };
  const capacity_buckets = { ...base.capacity_buckets, ...add.capacity_buckets };
  const over = { ...base.over, ...add.over };

  // A task spanning a fetch boundary IS returned by both windows — dedupe by
  // id. Its hours still land in different period keys on either side, so the
  // buckets above stay correct.
  const byId = new Map<string, TWorkloadTask>();
  for (const t of [...base.tasks, ...add.tasks]) byId.set(t.id, t);

  const total = Object.values(buckets).reduce((sum, h) => sum + h, 0);
  const totalCapacity = Object.values(capacity_buckets).reduce((sum, h) => sum + h, 0);

  return {
    ...base,
    buckets,
    month_buckets,
    capacity_buckets,
    over,
    tasks: [...byId.values()],
    // Recomputed, never merged: both are aggregates OVER the merged buckets,
    // so carrying either window's figure forward would describe a window that
    // no longer exists.
    total: Math.round(total * 100) / 100,
    total_over: total > totalCapacity,
    tasks_truncated: base.tasks_truncated || add.tasks_truncated,
  };
}

/**
 * Fold a freshly fetched window into what is already held.
 *
 * `unscheduled` and `meta` are taken from `add` rather than combined:
 * `spread_estimate` routes a task with no target date to the Unscheduled bucket
 * REGARDLESS of the window, so every response repeats the same unscheduled
 * totals — adding them would multiply the figure by the number of pans.
 */
export function mergeWorkloadResponses(base: TWorkloadResponse | null, add: TWorkloadResponse): TWorkloadResponse {
  if (!base || base.granularity !== add.granularity) return add;

  const rows = new Map<string, TWorkloadRow>();
  for (const row of base.rows) rows.set(rowKey(row), row);
  for (const row of add.rows) {
    const key = rowKey(row);
    const existing = rows.get(key);
    rows.set(key, existing ? mergeRow(existing, row) : row);
  }

  const merged = [...rows.values()];
  // Reproduce the API's order EXACTLY (service.py `compute_workload`:
  // `rows.sort(key=lambda r: (r["assignee_id"] is not None, r["assignee_name"].casefold()))`)
  // so a merge never reshuffles the board under the reader.
  //
  // Unassigned first, keyed on `assignee_id == null` rather than on the display
  // name, so a real member literally called "Unassigned" still sorts under U —
  // the same distinction the server makes. Then case-insensitive by name;
  // `sensitivity: "accent"` is the JS analogue of Python's `casefold()`
  // (ignores case, still distinguishes accented letters).
  //
  // This sorted by `total` DESCENDING until 2026-08-22, left behind when #46
  // moved the server to alphabetical and updated only the server. The comment
  // here claimed the two matched, which is why review kept passing over it. The
  // first paint looked correct because a first fetch has no base to merge with
  // (see the early return above) — the board only re-sorted once the reader
  // scrolled and a second range merged in.
  const sortedRows = merged.toSorted(
    (a, b) =>
      Number(a.assignee_id != null) - Number(b.assignee_id != null) ||
      a.assignee_name.localeCompare(b.assignee_name, undefined, { sensitivity: "accent" })
  );

  return {
    granularity: add.granularity,
    date_from: base.date_from < add.date_from ? base.date_from : add.date_from,
    date_to: base.date_to > add.date_to ? base.date_to : add.date_to,
    periods: [...new Set([...base.periods, ...add.periods])].toSorted(),
    rows: sortedRows,
    unscheduled: add.unscheduled,
    meta: add.meta,
  };
}

// ── Lane packing ─────────────────────────────────────────────────────────────

/**
 * Greedy interval partitioning: pack tasks into the fewest rows such that no
 * two tasks in a row overlap in time.
 *
 * Sort by start, then place each task in the FIRST lane whose last bar has
 * already ended. This is the classic algorithm and is optimal — it uses exactly
 * as many lanes as the maximum number of tasks in flight at any instant, which
 * is the true lower bound (you cannot draw N simultaneous bars in fewer than N
 * rows). Sorting by start is what makes the first-fit choice safe: every
 * later task starts no earlier, so a lane that is free now stays free.
 *
 * Adjacency counts as a collision. Two bars where one ends the same day the
 * next begins are drawn touching, and the API's own semantics make that a real
 * overlap — an issue with `start == target` occupies that whole day. Requiring
 * a strict gap keeps them on separate rows rather than rendering them fused.
 */
/**
 * How many unscheduled bars a swimlane draws before the footer takes over.
 *
 * A height budget, not a display preference. Every unscheduled task is drawn on
 * its OWN row — they all sit on the same column, so they cannot share one the
 * way `packTasksIntoLanes` lets scheduled tasks share — which means a member
 * with 30 unscheduled items would be 30 rows tall and push everyone else off
 * the screen. Whatever this cap hides, the footer counts.
 */
export const MAX_UNSCHEDULED_LANES = 3;

export type TUnscheduledSelection = {
  /** At most `maxLanes`, in server order. */
  shown: TWorkloadTask[];
  /** How many unscheduled tasks the cap left out. 0 when everything fits. */
  hiddenCount: number;
};

/**
 * Split a row's unscheduled tasks into the ones to draw and a count of the rest.
 *
 * `unscheduled` means `!task.target_date` — the exact predicate
 * `packTasksIntoLanes` filters OUT, and the one the footer has always counted.
 * The two must stay complements: any task the packer drops is a task this
 * selector has to see, or that work disappears from the board entirely.
 *
 * Server order is preserved deliberately — no sort here. `service.py`'s
 * `_task_sort_key` already ordered `tasks` by
 * `(start is None, start, target is None, target)`, so within the unscheduled
 * group a task carrying a start sorts ahead of one carrying nothing. Re-sorting
 * would fight that and make the three shown bars swap places between refetches
 * for no reason the reader could see.
 */
export function selectUnscheduledTasks(
  tasks: TWorkloadTask[],
  maxLanes: number = MAX_UNSCHEDULED_LANES
): TUnscheduledSelection {
  // `filter` returns a new array, so nothing in the store's response object is
  // touched — the same reason `packTasksIntoLanes` filters before it sorts.
  const unscheduled = tasks.filter((t) => !t.target_date);
  const limit = Math.max(0, maxLanes);
  return {
    shown: unscheduled.slice(0, limit),
    hiddenCount: Math.max(0, unscheduled.length - limit),
  };
}

/**
 * The date column an unscheduled bar is drawn in.
 *
 * A task with a `start_date` but no `target_date` is unscheduled by this
 * codebase's definition — both `packTasksIntoLanes` and the footer key on
 * `target_date` alone — but it already carries a date somebody chose. Drawing it
 * at today would overwrite that choice visually, and once these bars are
 * draggable a bar's position is a claim about a date. Only the genuinely
 * dateless case falls back to today.
 *
 * `todayISO` is a parameter rather than a `new Date()` inside, so this stays
 * pure and testable against a fixed day.
 */
export function unscheduledAnchorDate(task: TWorkloadTask, todayISO: string): string {
  return task.start_date ?? todayISO;
}

export function packTasksIntoLanes(tasks: TWorkloadTask[]): TWorkloadTask[][] {
  // `filter` already returns a new array, so the subsequent in-place sort never
  // touches `tasks` — which matters, since that array belongs to the store's
  // response object and sorting it during a render would mutate observable state.
  const scheduled = tasks.filter((t) => t.target_date);
  scheduled.sort((a, b) => {
    const aStart = a.start_date ?? a.target_date ?? "";
    const bStart = b.start_date ?? b.target_date ?? "";
    return aStart < bStart ? -1 : aStart > bStart ? 1 : 0;
  });

  const lanes: TWorkloadTask[][] = [];
  const laneEnds: string[] = [];

  for (const task of scheduled) {
    // A task with only a target date occupies that single day.
    const start = task.start_date ?? task.target_date!;
    const end = task.target_date!;
    const lane = laneEnds.findIndex((laneEnd) => laneEnd < start);
    if (lane === -1) {
      lanes.push([task]);
      laneEnds.push(end);
    } else {
      lanes[lane].push(task);
      // Never move the end backwards: a long bar placed earlier still occupies
      // this lane past a shorter one appended after it.
      if (end > laneEnds[lane]) laneEnds[lane] = end;
    }
  }
  return lanes;
}
