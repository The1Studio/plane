/**
 * Date-range helpers for the workload toolbar.
 *
 * Extracted from WorkloadMatrix so the span clamp stays owned by this package
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
 * Clamp a range to the granularity's max span, moving the edge the user did
 * NOT just set. `anchor` names the edge the user changed — it is held fixed.
 *
 * The API rejects an over-long span with a 400 (`views.py` `_SPAN_CAPS`), so
 * clamping here keeps the request valid instead of surfacing a server error.
 */
export function clampDateRange(
  from: string,
  to: string,
  granularity: TWorkloadGranularity,
  anchor: "from" | "to"
): { from: string; to: string } {
  const max = MAX_SPAN_DAYS[granularity];
  if (daysBetween(from, to) <= max) return { from, to };
  return anchor === "from" ? { from, to: shiftDate(from, max) } : { from: shiftDate(to, -max), to };
}
