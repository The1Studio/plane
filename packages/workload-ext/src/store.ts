import { action, computed, makeObservable, observable, runInAction } from "mobx";
import { WorkloadService } from "./service";
import type { TWorkloadEstimate, TWorkloadFilters, TWorkloadGranularity, TWorkloadResponse } from "./types";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Format a Date as YYYY-MM-DD (local timezone). */
function toDateString(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Add `weeks` weeks to a date and return a new Date. */
function addWeeks(d: Date, weeks: number): Date {
  const result = new Date(d);
  result.setDate(result.getDate() + weeks * 7);
  return result;
}

// ── Interface ─────────────────────────────────────────────────────────────────

export interface IWorkloadStore {
  // observables
  granularity: TWorkloadGranularity;
  dateFrom: string;
  dateTo: string;
  selectedProjectIds: string[];
  selectedAssigneeIds: string[];
  selectedStateGroups: string[];
  workloadData: TWorkloadResponse | null;
  estimateData: Record<string, TWorkloadEstimate | null>; // keyed by issueId
  isLoading: boolean;
  error: string | null;

  // computed
  maxColumns: number;

  // actions
  setGranularity: (g: TWorkloadGranularity) => void;
  setDateRange: (from: string, to: string) => void;
  setProjectIds: (ids: string[]) => void;
  setAssigneeIds: (ids: string[]) => void;
  setStateGroups: (groups: string[]) => void;
  fetchWorkload: (workspaceSlug: string) => Promise<void>;
  fetchEstimate: (workspaceSlug: string, projectId: string, issueId: string) => Promise<void>;
  updateEstimate: (workspaceSlug: string, projectId: string, issueId: string, hours: number) => Promise<void>;
  deleteEstimate: (workspaceSlug: string, projectId: string, issueId: string) => Promise<void>;
}

// ── Store ─────────────────────────────────────────────────────────────────────

export class WorkloadStore implements IWorkloadStore {
  // observables
  granularity: TWorkloadGranularity = "week";
  dateFrom: string;
  dateTo: string;
  selectedProjectIds: string[] = [];
  selectedAssigneeIds: string[] = [];
  selectedStateGroups: string[] = [];
  workloadData: TWorkloadResponse | null = null;
  estimateData: Record<string, TWorkloadEstimate | null> = {};
  isLoading: boolean = false;
  error: string | null = null;

  private readonly service: WorkloadService;

  constructor() {
    const today = new Date();
    this.dateFrom = toDateString(today);
    this.dateTo = toDateString(addWeeks(today, 12));
    this.service = new WorkloadService();

    makeObservable(this, {
      granularity: observable,
      dateFrom: observable,
      dateTo: observable,
      selectedProjectIds: observable,
      selectedAssigneeIds: observable,
      selectedStateGroups: observable,
      workloadData: observable,
      estimateData: observable,
      isLoading: observable,
      error: observable,

      maxColumns: computed,

      setGranularity: action,
      setDateRange: action,
      setProjectIds: action,
      setAssigneeIds: action,
      setStateGroups: action,
      fetchWorkload: action,
      fetchEstimate: action,
      updateEstimate: action,
      deleteEstimate: action,
    });
  }

  // ── Computed ───────────────────────────────────────────────────────────────

  get maxColumns(): number {
    const caps: Record<TWorkloadGranularity, number> = {
      day: 62,
      week: 52,
      month: 24,
    };
    return caps[this.granularity];
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  setGranularity(g: TWorkloadGranularity): void {
    this.granularity = g;
  }

  setDateRange(from: string, to: string): void {
    this.dateFrom = from;
    this.dateTo = to;
  }

  setProjectIds(ids: string[]): void {
    this.selectedProjectIds = ids;
  }

  setAssigneeIds(ids: string[]): void {
    this.selectedAssigneeIds = ids;
  }

  setStateGroups(groups: string[]): void {
    this.selectedStateGroups = groups;
  }

  async fetchWorkload(workspaceSlug: string): Promise<void> {
    const filters: TWorkloadFilters = {
      granularity: this.granularity,
      date_from: this.dateFrom,
      date_to: this.dateTo,
      ...(this.selectedProjectIds.length > 0 && { project_ids: this.selectedProjectIds }),
      ...(this.selectedAssigneeIds.length > 0 && { assignee_ids: this.selectedAssigneeIds }),
      ...(this.selectedStateGroups.length > 0 && { state_group: this.selectedStateGroups }),
    };

    runInAction(() => {
      this.isLoading = true;
      this.error = null;
    });

    try {
      const data = await this.service.getWorkload(workspaceSlug, filters);
      runInAction(() => {
        this.workloadData = data;
        this.isLoading = false;
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
        this.isLoading = false;
      });
    }
  }

  async fetchEstimate(workspaceSlug: string, projectId: string, issueId: string): Promise<void> {
    try {
      const estimate = await this.service.getEstimate(workspaceSlug, projectId, issueId);
      runInAction(() => {
        this.estimateData[issueId] = estimate;
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
    }
  }

  async updateEstimate(workspaceSlug: string, projectId: string, issueId: string, hours: number): Promise<void> {
    try {
      const estimate = await this.service.putEstimate(workspaceSlug, projectId, issueId, hours);
      runInAction(() => {
        this.estimateData[issueId] = estimate;
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
    }
  }

  async deleteEstimate(workspaceSlug: string, projectId: string, issueId: string): Promise<void> {
    try {
      await this.service.deleteEstimate(workspaceSlug, projectId, issueId);
      runInAction(() => {
        this.estimateData[issueId] = null;
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
    }
  }
}
