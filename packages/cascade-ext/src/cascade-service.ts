/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  TCascadeApplyResponse,
  TCascadePreviewResponse,
  TCascadeStateGroup,
  TModuleCascadeApplyResponse,
  TModuleCascadePreviewResponse,
  TModuleCascadeStatus,
} from "./types";

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

  /**
   * `GET …/modules/<module_id>/cascade-preview/?status=<completed|cancelled>` — the module
   * equivalent of `getPreview`. The query param is `status` (a MODULE status), NOT `group` — the
   * two endpoints intentionally use different param names so they can never be confused
   * (phase-1 § Endpoint contract). Read-only; safe to call speculatively, guarded first by
   * `shouldPromptModuleCascade`.
   */
  async getModulePreview(
    workspaceSlug: string,
    projectId: string,
    moduleId: string,
    status: TModuleCascadeStatus
  ): Promise<TModuleCascadePreviewResponse> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/modules/${moduleId}/cascade-preview/?status=${status}`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new CascadeApiError(await res.text(), res.status);
    return res.json() as Promise<TModuleCascadePreviewResponse>;
  }

  /**
   * `POST …/modules/<module_id>/cascade-apply/` — applies the module's new `status` and the
   * caller-selected item ids in one server-side transaction (M5). Unlike the issue path's
   * `apply`, `itemIds` is always an explicit array here, never `null` — the UI must never request
   * "every eligible item" implicitly (phase-2 § Implementation item 3); a headless/MCP caller that
   * wants that behavior omits the key at the HTTP layer directly rather than through this method.
   * The server re-derives eligibility itself and never trusts this list as authorization
   * (mirrors the issue path's risk-15 mitigation).
   */
  async applyModuleCascade(
    workspaceSlug: string,
    projectId: string,
    moduleId: string,
    status: TModuleCascadeStatus,
    itemIds: string[]
  ): Promise<TModuleCascadeApplyResponse> {
    const url = `${API_BASE}/workspaces/${workspaceSlug}/projects/${projectId}/modules/${moduleId}/cascade-apply/`;
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, item_ids: itemIds }),
    });
    if (!res.ok) throw new CascadeApiError(await res.text(), res.status);
    return res.json() as Promise<TModuleCascadeApplyResponse>;
  }
}

/** Ready-made singleton — the shape Phase 3 wires directly into its two store choke points. */
export const cascadeService = new CascadeService();
