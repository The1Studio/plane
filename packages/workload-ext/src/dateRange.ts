/**
 * Date-range helpers for the workload toolbar.
 *
 * Extracted from the (now-deleted) aggregate table so the span clamp stays owned by this package
 * even though the date-picker UI is now injected by the host app (the app can
 * only render Plane's DateRangeDropdown; it must not re-derive the clamp rules).
 */

import type { TWorkloadGranularity } from "./types";

/** Max date-range span in days per granularity. Mirrors `_SPAN_CAPS` in the API's views.py. */
export const MAX_SPAN_DAYS: Record<TWorkloadGranularity, number> = {
  day: 92,
  week: 366,
  month: 730,
};

/**
 * Add/subtract days from a YYYY-MM-DD string, returning YYYY-MM-DD.
 *
 * The `T00:00:00` suffix is load-bearing, not decoration. A bare `YYYY-MM-DD`
 * is parsed by `Date` as **UTC** midnight, while `getDate()`/`getMonth()`/
 * `getFullYear()` below read the **local** calendar — so at any negative UTC
 * offset the local date is already the previous day before a single day is
 * added, and every result comes back 24h early. Appending a time makes the
 * string parse as local, which is the same calendar the getters use. Same
 * idiom, same reason, as `periodKeyFor` in ./merge.ts.
 *
 * This is not hypothetical for callers: `periodDateRange` uses this to derive
 * a week bucket's END date, and the workload timeline positions its capacity
 * heat cells from that range — an off-by-one here shifts every cell in the
 * header row for anyone west of Greenwich.
 */
export function shiftDate(dateStr: string, days: number): string {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Compute day difference between two YYYY-MM-DD strings.
 *
 * Deliberately keeps the bare (UTC) parse that `shiftDate` above had to drop:
 * this only ever subtracts two instants, both offset identically, so the result
 * is an exact multiple of 86_400_000 and no local calendar is consulted.
 * Switching these to a local parse for symmetry would reintroduce DST — a
 * spring-forward day is 23h — which is precisely what the UTC parse avoids.
 */
export function daysBetween(from: string, to: string): number {
  return Math.round((new Date(to).getTime() - new Date(from).getTime()) / 86_400_000);
}

/**
 * The [start, end] (inclusive, both YYYY-MM-DD) calendar span a `periods[]`
 * bucket key covers, for the Phase 8 timeline's capacity heat row. Mirrors
 * `period_key()` in `apps/api/plane/workload/aggregation.py` — the key format
 * is granularity-dependent and this is the single place that reverses it:
 *
 * - `day`   — the key IS the date: `"2026-08-17"` → span of that one day.
 * - `week`  — the key IS the week's first date (an arbitrary week-start day,
 *   never an ISO week number — plan D10): `"2026-08-17"` → that date plus 6
 *   days. Do NOT re-derive the boundary from `week_start_day`; the key
 *   already IS the start.
 * - `month` — the key is `"YYYY-MM"`: `"2026-08"` → the 1st through the last
 *   calendar day of that month.
 */
export function periodDateRange(period: string, granularity: TWorkloadGranularity): { start: string; end: string } {
  if (granularity === "day") return { start: period, end: period };
  if (granularity === "week") return { start: period, end: shiftDate(period, 6) };
  // month: "YYYY-MM" — end is the last day of that month.
  const [yearStr, monthStr] = period.split("-");
  const year = Number(yearStr);
  const month = Number(monthStr); // 1-indexed
  const lastDay = new Date(year, month, 0).getDate(); // day 0 of next month = last day of this month
  const end = `${yearStr}-${monthStr}-${String(lastDay).padStart(2, "0")}`;
  return { start: `${period}-01`, end };
}

/**
 * How many days in the inclusive range [from, to] fall on a configured workday.
 *
 * `workdays` uses Plane's EStartOfTheWeek encoding (SUN=0..SAT=6) — the SAME
 * encoding the API stores and returns, so no remapping happens here. JS's
 * `Date.getUTCDay()` already produces that encoding natively, which is why this
 * needs no counterpart to the backend's `to_plane_weekday()`.
 *
 * Dates are parsed as UTC and stepped by whole UTC days, so a viewer in any
 * timezone counts the same days for the same range. Unlike `shiftDate` above,
 * a bare `T00:00:00Z` (not local) parse is deliberate here: the count must not
 * depend on the caller's offset, only on the calendar dates themselves.
 */
export function countWorkdays(from: string, to: string, workdays: number[]): number {
  if (from > to) return 0;
  const workdaySet = new Set(workdays);
  const DAY_MS = 86_400_000;
  const start = new Date(`${from}T00:00:00Z`).getTime();
  const end = new Date(`${to}T00:00:00Z`).getTime();
  let count = 0;
  for (let t = start; t <= end; t += DAY_MS) {
    if (workdaySet.has(new Date(t).getUTCDay())) count++;
  }
  return count;
}
