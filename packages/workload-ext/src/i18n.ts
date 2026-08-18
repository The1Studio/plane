/**
 * Fork-owned i18n for the SP2 workload feature.
 *
 * The core `@plane/i18n` package must NOT be edited in place (docs/FORK.md —
 * no `@plane/*` edits), and its TranslationStore loads locale bundles
 * statically with no runtime registration API. So the workload feature ships
 * its own string table here, per the plan §5.6 ("ship strings inside the
 * package; English required, others fall back").
 *
 * English is the only bundled locale today; `wlt` is the single seam to extend
 * if other locales are added later. Keys are flat dotted strings to mirror the
 * core `t("namespace.key")` convention.
 *
 * Usage:
 *   import { wlt } from "@plane/workload-ext";
 *   wlt("matrix.assignee");                          // "Assignee"
 *   wlt("matrix.no_target_date", { percent: 40 });   // "40% of issues have no target date."
 */

import type { TWorkloadRollup } from "./types";

export const WORKLOAD_STRINGS = {
  "common.from": "From",
  "common.to": "To",
  "common.total": "Total",
  "common.none": "None",
  "common.loading": "Loading…",
  "common.saving": "saving…",
  "estimate.label": "Estimated hours",
  "estimate.tooltip": "Estimated: {hours}h",
  // Parent rollup — read-only display (sidebar, spreadsheet cell, list/kanban pill).
  // No ICU plurals: phrasing is written to read correctly for any count.
  "estimate.rollup_pill": "Σ {hours}h · {percent}%",
  "estimate.rollup_pill_no_percent": "Σ {hours}h",
  "estimate.rollup_tooltip": "From {count} sub-item(s) · due {date}",
  "estimate.rollup_tooltip_no_due": "From {count} sub-item(s)",
  "estimate.parent_has_children_toast_title": "Can't edit estimate",
  "estimate.parent_has_children_toast_message":
    "This work item now has sub-items — its estimate is calculated automatically from them.",
  "progress.label": "Progress",
  "matrix.assignee": "Assignee",
  "matrix.unscheduled": "Unscheduled",
  "matrix.no_data_loaded": "No data loaded yet.",
  "matrix.no_workload_data": "No workload data.",
  "matrix.no_target_date": "{percent}% of issues have no target date.",
  "matrix.issues_summary": "{counted} issues counted · {zero} with 0h estimate",
  "matrix.truncated": "Results truncated. Narrow your date range.",
  "matrix.over_capacity": "Over",
  "matrix.no_over_capacity": "No one is over capacity.",
  "granularity.day": "Day",
  "granularity.week": "Week",
  "granularity.month": "Month",
  "filters.projects": "Projects",
  "filters.members": "Members",
  "filters.granularity": "Granularity",
  "filters.state_groups": "Status",
  "filters.clear": "Clear filters",
  "filters.over_only": "Over capacity only",
  // Workspace work-settings readout (The1Studio fork — workspace work settings, phase-4.md).
  "toolbar.settings_readout": "Max {hours}h/week · {workdays} · week starts {weekStart}",
  "toolbar.manage_settings": "Manage",
  // Timeline (The1Studio fork — Phase 8, replaces the matrix).
  "timeline.unassigned": "Unassigned",
  "timeline.unscheduled_count": "Unscheduled ({count})",
  "timeline.overdue_count": "Overdue ({count})",
  "timeline.showing_first_n": "Showing first {count} — narrow your filters to see the rest",
  "timeline.no_workload_data": "No workload data.",
} as const;

export type TWorkloadStringKey = keyof typeof WORKLOAD_STRINGS;

/**
 * Translate a workload string key, interpolating `{name}` placeholders from
 * `params`. English-only; unknown placeholders are left intact.
 */
export function wlt(key: TWorkloadStringKey, params?: Record<string, string | number>): string {
  const template = WORKLOAD_STRINGS[key];
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_match, name: string) =>
    name in params ? String(params[name]) : `{${name}}`
  );
}

// ── Parent rollup display formatting ────────────────────────────────────────
//
// Shared by the sidebar estimate field, the spreadsheet estimated-hours
// column, and the list/kanban hours pill (plan §P4 item 5) — kept here
// (rather than duplicated three times) since the output is composed directly
// from these wlt() templates.

/** `rollup.percent` is a 0..1 fraction; round to a whole percent for display. */
function toDisplayPercent(percent: number): number {
  return Math.round(percent * 100);
}

/** "Σ 10h · 60%", or "Σ 10h" when percent is null (hours === 0). */
export function formatRollupPill(rollup: TWorkloadRollup): string {
  if (rollup.percent === null) return wlt("estimate.rollup_pill_no_percent", { hours: rollup.hours });
  return wlt("estimate.rollup_pill", { hours: rollup.hours, percent: toDisplayPercent(rollup.percent) });
}

/**
 * "Σ 10h" — hours only, no percent. Used by the hours surfaces (sidebar field,
 * spreadsheet Estimated-hours column, list/kanban hours pill) now that progress
 * has its own dedicated bar column/row; keeps hours and progress cleanly split.
 */
export function formatRollupHours(rollup: TWorkloadRollup): string {
  return wlt("estimate.rollup_pill_no_percent", { hours: rollup.hours });
}

/** "From 3 sub-item(s) · due 2026-08-01", or without the due-date clause. */
export function formatRollupTooltip(rollup: TWorkloadRollup): string {
  if (rollup.due_date) {
    return wlt("estimate.rollup_tooltip", { count: rollup.leaf_count, date: rollup.due_date });
  }
  return wlt("estimate.rollup_tooltip_no_due", { count: rollup.leaf_count });
}
