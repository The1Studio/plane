import type { TWorkloadEstimate, TWorkloadFilters, TWorkloadResponse } from "./types";

const API_BASE = "/api";

/**
 * Maximum number of issue IDs per bulk-estimates chunk.
 * This is a client-side split limit; the backend cap is 500.
 * The two values are independent — the client uses 400 to stay safely under
 * the server limit while keeping chunks a manageable size.
 */
const BULK_CHUNK_SIZE = 400;

export class WorkloadService {
  // ── Estimate CRUD ──────────────────────────────────────────────────────────

  async getEstimate(workspaceSlug: string, projectId: string, issueId: string): Promise<TWorkloadEstimate | null> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/workload-estimate/`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(await res.text());
    const data = (await res.json()) as { hours: number | null } & Partial<TWorkloadEstimate>;
    if (data.hours === null || data.hours === undefined) return null;
    return data as TWorkloadEstimate;
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
    if (!res.ok) throw new Error(await res.text());
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
