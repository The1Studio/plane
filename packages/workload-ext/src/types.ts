export type TWorkloadGranularity = "day" | "week" | "month";

export type TWorkloadRow = {
  assignee_id: string | null;
  assignee_name: string;
  buckets: Record<string, number>; // sparse: period key → hours
  total: number;
  /**
   * Per-person weekly capacity, prorated per period, keyed by the SAME period
   * columns as `buckets` (spans every period in the response, not just the
   * populated ones — so a capacity reference renders even on zero-hour
   * periods). Members with no workspace-wide capacity row get `{}`.
   */
  capacity_buckets?: Record<string, number>;
  /**
   * Hours per WEEK, independent of `granularity` — the basis for the
   * `NNh/40h` badge and for the over-capacity signal, both of which are
   * defined per week however the columns happen to be bucketed. Sparse.
   *
   * The key is the containing week's FIRST DATE (`"2026-08-17"`), never an
   * ISO week number — an arbitrary `week_start_day` has none. Same convention
   * as a `week`-granularity `buckets` key, so `periodDateRange(k, "week")`
   * reverses it.
   */
  weekly_buckets?: Record<string, number>;
  /** The workspace-wide weekly max (`max_weekly_hours`) — the badge's denominator. */
  weekly_capacity?: number;
  /** Per-period overload flag, keyed identically to `capacity_buckets`. */
  over?: Record<string, boolean>;
  /** True when `total` exceeds the sum of this row's `capacity_buckets`. */
  total_over?: boolean;
  /**
   * Per-task rows for the Phase 8 timeline (apps/api/plane/workload/service.py
   * "Phase 7 — per-task rows for the timeline"). Capped at 200 per assignee
   * server-side — see `tasks_truncated`. `hours` on each task is the ISSUE'S
   * WHOLE estimate, not the windowed slice `buckets` sums to; the two
   * deliberately do not reconcile for a task clipped by [date_from, date_to].
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
  /** The issue's whole estimate (not the windowed `buckets` slice). */
  hours: number;
  start_date: string | null;
  target_date: string | null;
  state_group: string;
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
