import React from "react";
import { observer } from "mobx-react";
import { Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell } from "@plane/propel/table";

import { wlt } from "./i18n";
import type { IWorkloadStore } from "./store";
import { WorkloadToolbar } from "./WorkloadToolbar";

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
  /** Forwarded verbatim to WorkloadToolbar — see its prop docs for why slots exist. */
  memberFilterSlot?: React.ReactNode;
  projectFilterSlot?: React.ReactNode;
  dateRangeSlot?: React.ReactNode;
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
      <span className="rounded bg-layer-1 px-1.5 py-0.5 text-11 text-tertiary">
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
      className="w-16 rounded border border-subtle bg-surface-1 px-1 py-0.5 text-11 text-primary tabular-nums focus:ring-1 focus:ring-accent-strong focus:outline-none"
    />
  );
});

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Format hours value for display. Returns "—" for zero. */
function formatHours(value: number): string {
  if (value === 0) return "—";
  if (Number.isInteger(value)) return `${value}h`;
  return `${value.toFixed(1)}h`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export const WorkloadMatrix = observer(function WorkloadMatrix({
  store,
  workspaceSlug,
  isAdmin = false,
  memberFilterSlot,
  projectFilterSlot,
  dateRangeSlot,
}: WorkloadMatrixProps) {
  // ── Effects ────────────────────────────────────────────────────────────────

  // Capacities are workspace-scoped (not per-row), so fetch once per mount /
  // workspaceSlug change rather than threading them through fetchWorkload.
  React.useEffect(() => {
    if (workspaceSlug) store.fetchCapacities(workspaceSlug);
  }, [store, workspaceSlug]);

  // ── Loading / error / empty states ────────────────────────────────────────

  if (store.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="py-8 text-center text-13 text-tertiary">{wlt("common.loading")}</div>
      </div>
    );
  }

  if (store.error) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="py-4 text-13 text-danger-primary">{store.error}</div>
      </div>
    );
  }

  if (!store.workloadData) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="py-8 text-center text-13 text-placeholder">{wlt("matrix.no_data_loaded")}</div>
      </div>
    );
  }

  const { rows, periods, unscheduled, meta } = store.workloadData;

  if (rows.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {renderToolbar()}
        <div className="py-8 text-center text-13 text-placeholder">
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
              <TableCell colSpan={visiblePeriods.length + 3} className="py-6 text-center text-13 text-placeholder">
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
                        className="rounded bg-danger-subtle px-1.5 py-0.5 text-11 font-medium text-danger-primary"
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
                      className={[
                        "text-right tabular-nums",
                        isOver ? "bg-warning-subtle text-warning-primary" : "",
                      ].join(" ")}
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
      <div className="space-y-0.5 text-11 text-tertiary">
        <p>{wlt("matrix.issues_summary", { counted: meta.issues_counted, zero: meta.zero_estimate_count })}</p>
        {meta.truncated && <p className="text-warning-primary">{wlt("matrix.truncated")}</p>}
      </div>
    </div>
  );

  // ── Toolbar (inner fn so every early-return branch renders it identically) ──

  function renderToolbar() {
    return (
      <WorkloadToolbar
        store={store}
        workspaceSlug={workspaceSlug}
        memberFilterSlot={memberFilterSlot}
        projectFilterSlot={projectFilterSlot}
        dateRangeSlot={dateRangeSlot}
      />
    );
  }
});
