export type TWorkloadGranularity = "day" | "week" | "month";

export type TWorkloadRow = {
  assignee_id: string | null;
  assignee_name: string;
  buckets: Record<string, number>; // sparse: period key → hours
  /**
   * Hours per CALENDAR month ("2026-08"), independent of the requested
   * granularity. Sparse. Exists because a week bucket is keyed by the date its
   * week begins, so summing week buckets for a month credits a straddling week
   * entirely to the month it started in — see plan D6.
   */
  month_buckets?: Record<string, number>;
  total: number;
  /**
   * Per-person weekly capacity, prorated per period, keyed by the SAME period
   * columns as `buckets` (spans every period in the response, not just the
   * populated ones — so a capacity reference renders even on zero-hour
   * periods). Members with no workspace-wide capacity row get `{}`.
   */
  capacity_buckets?: Record<string, number>;
  /** Per-period overload flag, keyed identically to `capacity_buckets`. */
  over?: Record<string, boolean>;
  /** True when `total` exceeds the sum of this row's `capacity_buckets`. */
  total_over?: boolean;
  /**
   * Per-task rows for the Phase 8 timeline (apps/api/plane/workload/service.py
   * "Phase 7 — per-task rows for the timeline"). Capped at 200 per assignee
   * server-side — see `tasks_truncated`. `hours` on each task is THIS ROW'S
   * ASSIGNEE'S SHARE of the issue's whole estimate (see `TWorkloadTask.hours`),
   * not the windowed slice `buckets` sums to; the two deliberately do not
   * reconcile for a task clipped by [date_from, date_to].
   */
  tasks: TWorkloadTask[];
  /** True when this row's `tasks` were truncated to the server-side cap (200). */
  tasks_truncated: boolean;
};

/**
 * One task row within `TWorkloadRow.tasks` — the per-issue detail the Phase 8
 * timeline renders as a bar. Mirrors the shape assembled in
 * `apps/api/plane/workload/service.py`'s `compute_workload`.
 */
export type TWorkloadTask = {
  id: string;
  /** Owning project — required to build a work-item link or open the peek panel. */
  project_id: string;
  /** `"<PROJECT>-<sequence_id>"`, e.g. "ENG-42". */
  identifier: string;
  name: string;
  /**
   * THIS row's assignee's share of the issue's estimate (not the windowed
   * `buckets` slice). A work item may carry several assignees, as in ClickUp;
   * its hours are split evenly across them, so a shared 8h task reports 4h on
   * each of two assignees' rows. Use `total_hours` for the undivided estimate.
   */
  hours: number;
  /** The issue's whole, undivided estimate — `hours * assignee_count`, modulo
   * the odd cent of an indivisible split. */
  total_hours: number;
  /** How many assignees the estimate was split across. 1 for an unshared task. */
  assignee_count: number;
  start_date: string | null;
  target_date: string | null;
  state_group: string;
  /**
   * The state's display name, e.g. "In Review". Server-normalised to `""`,
   * never null. This is the timeline bar's only legend: the bar is painted
   * with `state_color`, and a colour with nothing to read it by is not
   * information — the tooltip is where the reader learns which state that
   * hue means.
   */
  state_name: string;
  /**
   * The state's own colour, as a **free-form CSS colour string** — NOT a
   * guaranteed `#rrggbb`. Server-side this is `CharField(max_length=255)`
   * with no hex validation, so `""`, `#fa0`, `rgb(...)` and a named colour
   * are all reachable values.
   *
   * Two consequences, both load-bearing:
   *
   * - **Never parse it.** Do not slice an alpha suffix onto it to tint a
   *   fill (`state_color + "26"`); that breaks on every form above except
   *   6-digit hex. The bar tints by laying a translucent overlay over a
   *   full-opacity background, which needs no format assumption.
   * - **Never assume it is non-empty.** Route it through `stateBarColor`,
   *   which owns the fallback chain.
   */
  state_color: string;
  /** True when `target_date` is in the past and the issue isn't done/cancelled. */
  overdue: boolean;
};

export type TWorkloadUnscheduled = {
  assignee_id: string | null;
  hours: number;
};

export type TWorkloadMeta = {
  issues_counted: number;
  issues_unscheduled: number;
  unscheduled_ratio: number;
  dirty_date_count: number;
  zero_estimate_count: number;
  truncated: boolean;
};

export type TWorkloadResponse = {
  granularity: TWorkloadGranularity;
  date_from: string;
  date_to: string;
  periods: string[];
  rows: TWorkloadRow[];
  unscheduled: TWorkloadUnscheduled[];
  meta: TWorkloadMeta;
};

export type TWorkloadEstimate = {
  id: string;
  issue: string;
  hours: number;
  created_at: string;
  updated_at: string;
};

/**
 * Computed rollup for a parent issue — aggregated over its countable
 * descendants. `percent` is a 0..1 fraction (round(done/hours, 4) server
 * side), null when `hours` is 0. `due_date` is `YYYY-MM-DD` or null.
 * See plan §1 "Semantics" for the exact aggregation rules.
 */
export type TWorkloadRollup = {
  hours: number;
  done_hours: number;
  percent: number | null;
  due_date: string | null;
  leaf_count: number;
};

/**
 * Raw shape of `GET .../workload-estimate/` (single-issue). For a parent
 * issue `hours` is always `null` (the stored legacy value never leaks to the
 * UI) and `rollup` carries the aggregated values instead.
 */
export type TWorkloadEstimateGetResponse = Partial<TWorkloadEstimate> & {
  hours: number | null;
  is_parent?: boolean;
  rollup?: TWorkloadRollup | null;
};

/** `error_code` returned by `PUT .../workload-estimate/` when the target issue is a parent. */
export const PARENT_HAS_CHILDREN_ERROR_CODE = "PARENT_HAS_CHILDREN";

// Intersection type — do NOT extend @plane/types TBaseIssue directly
export type TIssueWithWorkload = {
  workload_estimate?: { hours: number };
};

export type TWorkloadFilters = {
  granularity: TWorkloadGranularity;
  date_from: string; // YYYY-MM-DD
  date_to: string; // YYYY-MM-DD
  project_ids?: string[];
  assignee_ids?: string[];
  state_group?: string[];
};
