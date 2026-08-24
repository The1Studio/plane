/**
 * The1Studio fork (work-item creation defaults).
 *
 * The values the create surfaces prefill so a user SEES the defaults and can
 * change or clear them before saving. The backend applies the same rule
 * independently (plane/issue_defaults_ext/defaults.py) for callers that send
 * no such fields at all — the API, the MCP server, the SDKs.
 *
 * Both halves are needed, and neither is redundant. The backend treats an
 * absent field and an explicit empty one as different things: `[]` and `null`
 * mean "deliberately nobody" / "deliberately no due date". The modal always
 * submits both keys, so without this prefill it would always be saying
 * "deliberately empty" and the backend default would never fire for the UI.
 *
 * Contract: plans/260824-workitem-creation-defaults/phase-5.md
 */

import type { TIssue } from "@plane/types";
import { renderFormattedPayloadDate } from "@plane/utils";

/**
 * Creation-time prefill: assign the creator, due today.
 *
 * Returns an empty object when the current user is not yet loaded, so a
 * half-hydrated store can never produce `assignee_ids: [undefined]`.
 *
 * The date comes from the browser's LOCAL day. The server computes its own
 * default in the creator's stored timezone for exactly this reason — a UTC
 * server and a UTC+7 browser would otherwise disagree by a day every morning.
 */
export const getWorkItemCreationDefaults = (currentUserId: string | undefined | null): Partial<TIssue> => {
  if (!currentUserId) return {};

  return {
    assignee_ids: [currentUserId],
    target_date: renderFormattedPayloadDate(new Date()) ?? null,
  };
};
