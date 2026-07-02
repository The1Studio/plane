import type {
  TWorkloadEstimate,
  TWorkloadEstimateGetResponse,
  TWorkloadFilters,
  TWorkloadResponse,
  TWorkloadRollup,
} from "./types";

const API_BASE = "/api";

/**
 * Typed error thrown by `putEstimate` when the PUT is rejected. Carries the
 * backend's `error_code` (e.g. `PARENT_HAS_CHILDREN`) so callers can react to
 * specific failure reasons instead of string-matching the message.
 */
export class WorkloadEstimateApiError extends Error {
  readonly errorCode?: string;

  constructor(message: string, errorCode?: string) {
    super(message);
    this.name = "WorkloadEstimateApiError";
    this.errorCode = errorCode;
  }
}

/**
 * Maximum number of issue IDs per bulk-estimates chunk.
 * This is a client-side split limit; the backend cap is 500.
 * The two values are independent — the client uses 400 to stay safely under
 * the server limit while keeping chunks a manageable size.
 */
const BULK_CHUNK_SIZE = 400;

export class WorkloadService {
  // ── Estimate CRUD ──────────────────────────────────────────────────────────

  /**
   * Fetch the estimate for a single issue.
   *
   * For a leaf issue `estimate` carries the stored value (or null when no
   * estimate exists). For a parent issue `estimate` is always null — its
   * legacy stored value never leaks to the UI — and `rollup` carries the
   * aggregated hours/done_hours/percent/due_date/leaf_count instead.
   */
  async getEstimate(
    workspaceSlug: string,
    projectId: string,
    issueId: string
  ): Promise<{ estimate: TWorkloadEstimate | null; rollup: TWorkloadRollup | null }> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/workload-estimate/`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(await res.text());
    const data = (await res.json()) as TWorkloadEstimateGetResponse;
    const rollup = data.rollup ?? null;
    if (data.hours === null || data.hours === undefined) return { estimate: null, rollup };
    return { estimate: data as TWorkloadEstimate, rollup };
  }

  async putEstimate(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    hours: number
  ): Promise<TWorkloadEstimate> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/workload-estimate/`;
    const res = await fetch(url, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hours }),
    });
    if (!res.ok) {
      const raw = await res.text();
      let message = raw;
      let errorCode: string | undefined;
      try {
        const parsed = JSON.parse(raw) as { error?: string; error_code?: string };
        if (parsed && typeof parsed === "object") {
          message = parsed.error ?? raw;
          errorCode = parsed.error_code;
        }
      } catch {
        // Non-JSON error body — fall back to the raw text as the message.
      }
      throw new WorkloadEstimateApiError(message, errorCode);
    }
    return res.json() as Promise<TWorkloadEstimate>;
  }

  async deleteEstimate(workspaceSlug: string, projectId: string, issueId: string): Promise<void> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/workload-estimate/`;
    const res = await fetch(url, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw new Error(await res.text());
  }

  /**
   * Fetch estimated hours for many issues in one (or more) requests.
   *
   * Contract: GET /api/workspaces/<slug>/workload-estimates/?issue_ids=a,b,c
   * → { "<uuid>": <hours number> }   (missing issue = absent key)
   *
   * If `issueIds.length` exceeds BULK_CHUNK_SIZE the list is split into chunks
   * and the results are merged client-side.
   */
  async getEstimatesBulk(workspaceSlug: string, issueIds: string[]): Promise<Record<string, number>> {
    if (issueIds.length === 0) return {};

    // Split into chunks to stay under the backend cap.
    const chunks: string[][] = [];
    for (let i = 0; i < issueIds.length; i += BULK_CHUNK_SIZE) {
      chunks.push(issueIds.slice(i, i + BULK_CHUNK_SIZE));
    }

    const results = await Promise.all(
      chunks.map(async (chunk) => {
        const url = `${API_BASE}/workspaces/${workspaceSlug}/workload-estimates/?issue_ids=${chunk.join(",")}`;
        const res = await fetch(url, { credentials: "include" });
        if (!res.ok) throw new Error(await res.text());
        return res.json() as Promise<Record<string, number>>;
      })
    );

    return Object.assign({}, ...results) as Record<string, number>;
  }

  /**
   * Fetch computed rollups for many issues in one (or more) requests.
   *
   * Contract: GET /api/workspaces/<slug>/workload-rollups/?issue_ids=a,b,c
   * → { "<uuid>": TWorkloadRollup }   (non-parent issue = absent key)
   *
   * Same chunking contract as getEstimatesBulk (BULK_CHUNK_SIZE client-side
   * split, backend cap 500).
   */
  async getRollupsBulk(workspaceSlug: string, issueIds: string[]): Promise<Record<string, TWorkloadRollup>> {
    if (issueIds.length === 0) return {};

    const chunks: string[][] = [];
    for (let i = 0; i < issueIds.length; i += BULK_CHUNK_SIZE) {
      chunks.push(issueIds.slice(i, i + BULK_CHUNK_SIZE));
    }

    const results = await Promise.all(
      chunks.map(async (chunk) => {
        const url = `${API_BASE}/workspaces/${workspaceSlug}/workload-rollups/?issue_ids=${chunk.join(",")}`;
        const res = await fetch(url, { credentials: "include" });
        if (!res.ok) throw new Error(await res.text());
        return res.json() as Promise<Record<string, TWorkloadRollup>>;
      })
    );

    return Object.assign({}, ...results) as Record<string, TWorkloadRollup>;
  }

  // ── Workload matrix ────────────────────────────────────────────────────────

  async getWorkload(workspaceSlug: string, filters: TWorkloadFilters): Promise<TWorkloadResponse> {
    const params = this._buildParams(filters);
    const url = `${API_BASE}/workspaces/${workspaceSlug}/workload/?${params}`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(await res.text());
    return res.json() as Promise<TWorkloadResponse>;
  }

  async getProjectWorkload(
    workspaceSlug: string,
    projectId: string,
    filters: TWorkloadFilters
  ): Promise<TWorkloadResponse> {
    // Merge projectId into project_ids filter, deduplicating any already-set ids.
    const mergedFilters: TWorkloadFilters = {
      ...filters,
      project_ids: Array.from(new Set([...(filters.project_ids ?? []), projectId])),
    };
    return this.getWorkload(workspaceSlug, mergedFilters);
  }

  // ── Private helpers ────────────────────────────────────────────────────────

  private _buildParams(filters: TWorkloadFilters): string {
    const params = new URLSearchParams();
    params.set("granularity", filters.granularity);
    params.set("date_from", filters.date_from);
    params.set("date_to", filters.date_to);
    if (filters.project_ids && filters.project_ids.length > 0) {
      params.set("project_ids", filters.project_ids.join(","));
    }
    if (filters.assignee_ids && filters.assignee_ids.length > 0) {
      params.set("assignee_ids", filters.assignee_ids.join(","));
    }
    if (filters.state_group && filters.state_group.length > 0) {
      params.set("state_group", filters.state_group.join(","));
    }
    return params.toString();
  }
}
