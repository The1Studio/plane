// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// SP2 AI ext API client — thin fetch wrappers around the ai_ext endpoints.

const AI_BASE = "/api/ai";

export interface SearchResponse {
  answer: string;
  citations: Array<{ id: string; entity_type: string }>;
}

export interface IntakeDraftResponse {
  intake_issue_id: string;
  issue_id: string;
  draft: Record<string, unknown>;
  confidence: number | null;
  model: string | null;
}

export interface AutoCreateResponse {
  status: string;
  message: string;
}

/** POST /api/ai/<slug>/search/ */
export async function aiSearch(
  workspaceSlug: string,
  query: string,
  topK = 8,
): Promise<SearchResponse> {
  const res = await fetch(`${AI_BASE}/${workspaceSlug}/search/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK }),
    credentials: "include",
  });
  if (!res.ok) throw new Error(`AI search failed: ${res.status}`);
  return res.json() as Promise<SearchResponse>;
}

/** POST /api/ai/<slug>/projects/<projectId>/auto-create/ */
export async function aiAutoCreate(
  workspaceSlug: string,
  projectId: string,
  text: string,
): Promise<AutoCreateResponse> {
  const res = await fetch(
    `${AI_BASE}/${workspaceSlug}/projects/${projectId}/auto-create/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      credentials: "include",
    },
  );
  if (!res.ok) throw new Error(`AI auto-create failed: ${res.status}`);
  return res.json() as Promise<AutoCreateResponse>;
}

/** GET /api/ai/<slug>/projects/<projectId>/intake-draft/<intakeIssueId>/ */
export async function getIntakeDraft(
  workspaceSlug: string,
  projectId: string,
  intakeIssueId: string,
): Promise<IntakeDraftResponse> {
  const res = await fetch(
    `${AI_BASE}/${workspaceSlug}/projects/${projectId}/intake-draft/${intakeIssueId}/`,
    { credentials: "include" },
  );
  if (!res.ok) throw new Error(`Intake draft fetch failed: ${res.status}`);
  return res.json() as Promise<IntakeDraftResponse>;
}
