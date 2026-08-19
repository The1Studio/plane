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

/** Add/subtract days from a YYYY-MM-DD string, returning YYYY-MM-DD. */
export function shiftDate(dateStr: string, days: number): string {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Compute day difference between two YYYY-MM-DD strings. */
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
