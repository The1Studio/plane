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

export const WORKLOAD_STRINGS = {
  "common.from": "From",
  "common.to": "To",
  "common.total": "Total",
  "common.none": "None",
  "common.loading": "Loading…",
  "common.refresh": "Refresh",
  "common.saving": "saving…",
  "estimate.label": "Estimated hours",
  "estimate.tooltip": "Estimated: {hours}h",
  "matrix.assignee": "Assignee",
  "matrix.unscheduled": "Unscheduled",
  "matrix.no_data_loaded": "No data loaded yet.",
  "matrix.no_workload_data": "No workload data.",
  "matrix.no_target_date": "{percent}% of issues have no target date.",
  "matrix.issues_summary": "{counted} issues counted · {zero} with 0h estimate",
  "matrix.truncated": "Results truncated. Narrow your date range.",
  "granularity.day": "Day",
  "granularity.week": "Week",
  "granularity.month": "Month",
  "filters.projects": "Projects",
  "filters.assignees": "Assignees",
  "filters.no_projects": "No projects available",
  "filters.no_assignees": "No assignees available",
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
