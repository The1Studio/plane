export type TWorkloadGranularity = "day" | "week" | "month";

export type TWorkloadRow = {
  assignee_id: string | null;
  assignee_name: string;
  buckets: Record<string, number>; // sparse: period key → hours
  total: number;
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
