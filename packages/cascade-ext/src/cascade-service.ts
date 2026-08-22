import type { TCascadeApplyResponse, TCascadePreviewResponse, TCascadeStateGroup } from "./types";

const API_BASE = "/api/cascade-ext";

/**
 * Typed error thrown on a non-2xx response from either endpoint. Carries the raw response body
 * so a caller can surface the server's own message rather than a generic "request failed".
 */
export class CascadeApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "CascadeApiError";
    this.status = status;
  }
}

/**
 * Client for the two `cascade_ext` endpoints (phase-1 § Endpoint contract). Plain `fetch`,
 * matching `@plane/workload-ext`'s `WorkloadService` — no `@plane/services` `APIService`
 * subclass needed for two routes.
 */
export class CascadeService {
  /**
   * `GET …/cascade-preview/?group=<completed|cancelled>` — the flattened descendant tree with
   * eligibility per node. Read-only; safe to call speculatively (guarded by
   * `shouldPromptCascade` first so it's never called for a leaf or a non-terminal move).
   */
  async getPreview(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    targetGroup: TCascadeStateGroup
  ): Promise<TCascadePreviewResponse> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/cascade-preview/?group=${targetGroup}`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new CascadeApiError(await res.text(), res.status);
    return res.json() as Promise<TCascadePreviewResponse>;
  }

  /**
   * `POST …/cascade-apply/` — applies the parent's new state and the caller-selected child ids
   * in one server-side transaction. `childIds: null` means "every currently-eligible descendant"
   * (Decision 14); an explicit `[]` cascades nothing — only the parent moves. The server
   * re-derives eligibility itself and never trusts this list as authorization (phase-1 risk-15
   * mitigation), so a stale or tampered id here is rejected, not silently applied.
   */
  async apply(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    stateId: string,
    childIds: string[] | null
  ): Promise<TCascadeApplyResponse> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/cascade-apply/`;
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state_id: stateId, child_ids: childIds }),
    });
    if (!res.ok) throw new CascadeApiError(await res.text(), res.status);
    return res.json() as Promise<TCascadeApplyResponse>;
  }
}

/** Ready-made singleton — the shape Phase 3 wires directly into its two store choke points. */
export const cascadeService = new CascadeService();
