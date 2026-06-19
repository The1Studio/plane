import React from "react";
import { observer } from "mobx-react";
import { Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell } from "@plane/propel/table";

import type { IWorkloadStore } from "./store";
import type { TWorkloadGranularity } from "./types";

// ── Types ─────────────────────────────────────────────────────────────────────

type WorkloadMatrixProps = {
  store: IWorkloadStore;
  workspaceSlug: string;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Max date-range span in days per granularity. */
const MAX_SPAN_DAYS: Record<TWorkloadGranularity, number> = {
  day: 92,
  week: 366,
  month: 730,
};

/** Format hours value for display. Returns "—" for zero. */
function formatHours(value: number): string {
  if (value === 0) return "—";
  if (Number.isInteger(value)) return `${value}h`;
  return `${value.toFixed(1)}h`;
}

/** Add/subtract days from a YYYY-MM-DD string, returning YYYY-MM-DD. */
function shiftDate(dateStr: string, days: number): string {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Compute day difference between two YYYY-MM-DD strings. */
function daysBetween(from: string, to: string): number {
  return Math.round((new Date(to).getTime() - new Date(from).getTime()) / 86_400_000);
}

// ── Component ─────────────────────────────────────────────────────────────────

export const WorkloadMatrix = observer(function WorkloadMatrix({ store, workspaceSlug }: WorkloadMatrixProps) {
  // ── Toolbar handlers ───────────────────────────────────────────────────────

  function handleGranularityClick(g: TWorkloadGranularity) {
    store.setGranularity(g);
    store.fetchWorkload(workspaceSlug);
  }

  function handleDateChange(field: "from" | "to", value: string) {
    let from = store.dateFrom;
    let to = store.dateTo;

    if (field === "from") {
      from = value;
      // Enforce max span: if to is too far, clamp it
      const maxTo = shiftDate(from, MAX_SPAN_DAYS[store.granularity]);
      if (daysBetween(from, to) > MAX_SPAN_DAYS[store.granularity]) {
        to = maxTo;
      }
    } else {
      to = value;
      // Enforce max span: if from is too far back, clamp it
      const minFrom = shiftDate(to, -MAX_SPAN_DAYS[store.granularity]);
      if (daysBetween(from, to) > MAX_SPAN_DAYS[store.granularity]) {
        from = minFrom;
      }
    }

    store.setDateRange(from, to);
    store.fetchWorkload(workspaceSlug);
  }

  // ── Loading / error / empty states ────────────────────────────────────────

  if (store.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="text-sm text-gray-500 py-8 text-center">Loading…</div>
      </div>
    );
  }

  if (store.error) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="text-sm text-red-500 py-4">{store.error}</div>
      </div>
    );
  }

  if (!store.workloadData) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="text-sm text-gray-400 py-8 text-center">No data loaded yet.</div>
      </div>
    );
  }

  const { rows, periods, unscheduled, meta } = store.workloadData;

  if (rows.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="text-sm text-gray-400 py-8 text-center">
          No workload data.
          {meta.unscheduled_ratio > 0 && (
            <span className="ml-1">{Math.round(meta.unscheduled_ratio * 100)}% of issues have no target date.</span>
          )}
        </div>
      </div>
    );
  }

  // ── Visible columns ────────────────────────────────────────────────────────

  const visiblePeriods = periods.slice(0, store.maxColumns);

  // ── Footer sums ────────────────────────────────────────────────────────────

  const periodTotals: Record<string, number> = {};
  for (const period of visiblePeriods) {
    periodTotals[period] = rows.reduce((sum, row) => sum + (row.buckets[period] ?? 0), 0);
  }

  const totalUnscheduled = unscheduled.reduce((sum, u) => sum + u.hours, 0);
  const grandTotal = rows.reduce((sum, row) => sum + row.total, 0);

  // ── Unscheduled lookup ─────────────────────────────────────────────────────

  function getUnscheduled(assigneeId: string | null): number {
    const entry = unscheduled.find((u) => u.assignee_id === assigneeId);
    return entry?.hours ?? 0;
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-4">
      {renderToolbar()}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="min-w-[160px] text-left">Assignee</TableHead>
            {visiblePeriods.map((period) => (
              <TableHead key={period} className="min-w-[80px] text-right">
                {period}
              </TableHead>
            ))}
            <TableHead className="min-w-[90px] text-right">Unscheduled</TableHead>
            <TableHead className="min-w-[80px] text-right">Total</TableHead>
          </TableRow>
        </TableHeader>

        <TableBody>
          {rows.map((row) => {
            const unscheduledHours = getUnscheduled(row.assignee_id);
            return (
              <TableRow key={row.assignee_id ?? "unassigned"}>
                <TableCell className="font-medium">{row.assignee_name}</TableCell>
                {visiblePeriods.map((period) => (
                  <TableCell key={period} className="text-right tabular-nums">
                    {formatHours(row.buckets[period] ?? 0)}
                  </TableCell>
                ))}
                <TableCell className="text-right tabular-nums">{formatHours(unscheduledHours)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatHours(row.total)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>

        <TableFooter>
          <TableRow>
            <TableCell className="font-semibold">Total</TableCell>
            {visiblePeriods.map((period) => (
              <TableCell key={period} className="text-right font-semibold tabular-nums">
                {formatHours(periodTotals[period] ?? 0)}
              </TableCell>
            ))}
            <TableCell className="text-right font-semibold tabular-nums">{formatHours(totalUnscheduled)}</TableCell>
            <TableCell className="text-right font-semibold tabular-nums">{formatHours(grandTotal)}</TableCell>
          </TableRow>
        </TableFooter>
      </Table>

      {/* Meta info */}
      <div className="text-xs text-gray-500 space-y-0.5">
        <p>
          {meta.issues_counted} issues counted · {meta.zero_estimate_count} with 0h estimate
        </p>
        {meta.truncated && <p className="text-amber-600">Results truncated. Narrow your date range.</p>}
      </div>
    </div>
  );

  // ── Toolbar (extracted as inner function so it can be called in all branches) ──

  function renderToolbar() {
    const granularities: Array<{ value: TWorkloadGranularity; label: string }> = [
      { value: "day", label: "Day" },
      { value: "week", label: "Week" },
      { value: "month", label: "Month" },
    ];

    return (
      <div className="flex flex-wrap items-center gap-3">
        {/* Granularity toggle */}
        <div className="border-gray-200 flex overflow-hidden rounded border">
          {granularities.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => handleGranularityClick(value)}
              className={[
                "px-3 py-1.5 text-sm transition-colors",
                store.granularity === value
                  ? "bg-custom-primary-100 text-custom-primary-200 font-medium"
                  : "bg-white text-gray-600 hover:bg-gray-50",
              ].join(" ")}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Date range */}
        <div className="text-sm flex items-center gap-2">
          <label htmlFor="wl-matrix-from" className="text-gray-500">
            From
          </label>
          <input
            id="wl-matrix-from"
            type="date"
            value={store.dateFrom}
            onChange={(e) => handleDateChange("from", e.target.value)}
            className="border-gray-200 text-sm focus:ring-custom-primary-100 rounded border px-2 py-1 focus:ring-1 focus:outline-none"
          />
          <label htmlFor="wl-matrix-to" className="text-gray-500">
            To
          </label>
          <input
            id="wl-matrix-to"
            type="date"
            value={store.dateTo}
            min={store.dateFrom}
            max={shiftDate(store.dateFrom, MAX_SPAN_DAYS[store.granularity])}
            onChange={(e) => handleDateChange("to", e.target.value)}
            className="border-gray-200 text-sm focus:ring-custom-primary-100 rounded border px-2 py-1 focus:ring-1 focus:outline-none"
          />
        </div>
      </div>
    );
  }
});
