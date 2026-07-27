import React from "react";
import { observer } from "mobx-react";
import { Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell } from "@plane/propel/table";

import { wlt } from "./i18n";
import type { IWorkloadStore } from "./store";
import type { TWorkloadGranularity } from "./types";

// ── Types ─────────────────────────────────────────────────────────────────────

type WorkloadMatrixProps = {
  store: IWorkloadStore;
  workspaceSlug: string;
  /**
   * Whether the current viewer may edit per-person capacity. Capacity
   * CRUD is ADMIN-only server-side (D-B3); this package is context-agnostic
   * and has no access to the app's permission store, so the caller resolves
   * the role and passes it down. Defaults to read-only.
   */
  isAdmin?: boolean;
};

type CapacityBadgeProps = {
  store: IWorkloadStore;
  workspaceSlug: string;
  assigneeId: string;
  isAdmin: boolean;
};

/** Per-row capacity display: editable number input for admins, a read-only badge otherwise. */
const CapacityBadge = observer(function CapacityBadge({
  store,
  workspaceSlug,
  assigneeId,
  isAdmin,
}: CapacityBadgeProps) {
  const capacity = store.capacities[assigneeId];
  const [draft, setDraft] = React.useState<string>(capacity !== undefined ? String(capacity) : "");
  const [isSaving, setIsSaving] = React.useState(false);

  // Keep the draft in sync when the store value changes from elsewhere
  // (another tab's write, or the initial fetchCapacities resolving).
  React.useEffect(() => {
    setDraft(capacity !== undefined ? String(capacity) : "");
  }, [capacity]);

  if (!isAdmin) {
    if (capacity === undefined) return null;
    return (
      <span className="bg-gray-100 text-xs text-gray-600 rounded px-1.5 py-0.5">
        {wlt("matrix.cap_short", { hours: capacity })}
      </span>
    );
  }

  async function handleBlur() {
    const parsed = Number(draft);
    if (draft.trim() === "" || Number.isNaN(parsed) || parsed < 0 || parsed === capacity) {
      setDraft(capacity !== undefined ? String(capacity) : "");
      return;
    }
    setIsSaving(true);
    try {
      await store.updateCapacity(workspaceSlug, assigneeId, parsed);
    } catch {
      // Error is recorded on the store (store.error); revert the draft.
      setDraft(capacity !== undefined ? String(capacity) : "");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <input
      type="number"
      min={0}
      step={0.5}
      value={draft}
      disabled={isSaving}
      aria-label={wlt("matrix.capacity")}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={handleBlur}
      onClick={(e) => e.stopPropagation()}
      className="border-gray-200 focus:ring-custom-primary-100 text-xs w-16 rounded border px-1 py-0.5 tabular-nums focus:ring-1 focus:outline-none"
    />
  );
});

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

export const WorkloadMatrix = observer(function WorkloadMatrix({
  store,
  workspaceSlug,
  isAdmin = false,
}: WorkloadMatrixProps) {
  // ── Effects ────────────────────────────────────────────────────────────────

  // Capacities are workspace-scoped (not per-row), so fetch once per mount /
  // workspaceSlug change rather than threading them through fetchWorkload.
  React.useEffect(() => {
    if (workspaceSlug) store.fetchCapacities(workspaceSlug);
  }, [store, workspaceSlug]);

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
        <div className="text-sm text-gray-500 py-8 text-center">{wlt("common.loading")}</div>
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
        <div className="text-sm text-gray-400 py-8 text-center">{wlt("matrix.no_data_loaded")}</div>
      </div>
    );
  }

  const { rows, periods, unscheduled, meta } = store.workloadData;

  if (rows.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="text-sm text-gray-400 py-8 text-center">
          {wlt("matrix.no_workload_data")}
          {meta.unscheduled_ratio > 0 && (
            <span className="ml-1">
              {wlt("matrix.no_target_date", { percent: Math.round(meta.unscheduled_ratio * 100) })}
            </span>
          )}
        </div>
      </div>
    );
  }

  // ── Visible columns ────────────────────────────────────────────────────────

  const visiblePeriods = periods.slice(0, store.maxColumns);

  // ── Over-capacity filter ───────────────────────────────────────────────────
  // Client-side only (not a backend query param) — see plan D-B4.

  const visibleRows = store.showOverCapacityOnly ? rows.filter((row) => row.total_over) : rows;
  const visibleAssigneeIds = new Set(visibleRows.map((row) => row.assignee_id));

  // ── Footer sums ────────────────────────────────────────────────────────────
  // Computed over visibleRows so the footer stays consistent with what's shown.

  const periodTotals: Record<string, number> = {};
  for (const period of visiblePeriods) {
    periodTotals[period] = visibleRows.reduce((sum, row) => sum + (row.buckets[period] ?? 0), 0);
  }

  const totalUnscheduled = unscheduled
    .filter((u) => visibleAssigneeIds.has(u.assignee_id))
    .reduce((sum, u) => sum + u.hours, 0);
  const grandTotal = visibleRows.reduce((sum, row) => sum + row.total, 0);

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
            <TableHead className="min-w-[160px] text-left">{wlt("matrix.assignee")}</TableHead>
            {visiblePeriods.map((period) => (
              <TableHead key={period} className="min-w-[80px] text-right">
                {period}
              </TableHead>
            ))}
            <TableHead className="min-w-[90px] text-right">{wlt("matrix.unscheduled")}</TableHead>
            <TableHead className="min-w-[80px] text-right">{wlt("common.total")}</TableHead>
          </TableRow>
        </TableHeader>

        <TableBody>
          {visibleRows.length === 0 && store.showOverCapacityOnly && (
            <TableRow>
              <TableCell colSpan={visiblePeriods.length + 3} className="text-sm text-gray-400 py-6 text-center">
                {wlt("matrix.no_over_capacity")}
              </TableCell>
            </TableRow>
          )}
          {visibleRows.map((row) => {
            const unscheduledHours = getUnscheduled(row.assignee_id);
            return (
              <TableRow key={row.assignee_id ?? "unassigned"}>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <span>{row.assignee_name}</span>
                    {row.assignee_id && (
                      <CapacityBadge
                        store={store}
                        workspaceSlug={workspaceSlug}
                        assigneeId={row.assignee_id}
                        isAdmin={isAdmin}
                      />
                    )}
                    {row.total_over && (
                      <span
                        className="bg-red-100 text-xs text-red-700 rounded px-1.5 py-0.5 font-medium"
                        title={wlt("matrix.over_capacity")}
                      >
                        {wlt("matrix.over_capacity")}
                      </span>
                    )}
                  </div>
                </TableCell>
                {visiblePeriods.map((period) => {
                  const isOver = row.over?.[period] === true;
                  return (
                    <TableCell
                      key={period}
                      className={["text-right tabular-nums", isOver ? "bg-amber-50 text-amber-700" : ""].join(" ")}
                    >
                      {formatHours(row.buckets[period] ?? 0)}
                    </TableCell>
                  );
                })}
                <TableCell className="text-right tabular-nums">{formatHours(unscheduledHours)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatHours(row.total)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>

        <TableFooter>
          <TableRow>
            <TableCell className="font-semibold">{wlt("common.total")}</TableCell>
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
        <p>{wlt("matrix.issues_summary", { counted: meta.issues_counted, zero: meta.zero_estimate_count })}</p>
        {meta.truncated && <p className="text-amber-600">{wlt("matrix.truncated")}</p>}
      </div>
    </div>
  );

  // ── Toolbar (extracted as inner function so it can be called in all branches) ──

  function renderToolbar() {
    const granularities: Array<{ value: TWorkloadGranularity; label: string }> = [
      { value: "day", label: wlt("granularity.day") },
      { value: "week", label: wlt("granularity.week") },
      { value: "month", label: wlt("granularity.month") },
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
            {wlt("common.from")}
          </label>
          <input
            id="wl-matrix-from"
            type="date"
            value={store.dateFrom}
            onChange={(e) => handleDateChange("from", e.target.value)}
            className="border-gray-200 text-sm focus:ring-custom-primary-100 rounded border px-2 py-1 focus:ring-1 focus:outline-none"
          />
          <label htmlFor="wl-matrix-to" className="text-gray-500">
            {wlt("common.to")}
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
