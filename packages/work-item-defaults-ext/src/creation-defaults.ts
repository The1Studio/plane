/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
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
 *           plans/260825-workitem-defaults-project-change/phase-1.md
 */

import type { TIssue } from "@plane/types";
import { renderFormattedPayloadDate } from "@plane/utils";

/**
 * Everything needed to decide who a new work item is assigned to.
 *
 * The context is per-PROJECT, not per-user: the create modal lets the project
 * change while it is open, and the creator may not be assignable in whichever
 * project is chosen.
 */
export type TCreationAssigneeContext = {
  /** What the form holds right now. Absent at modal open. */
  currentAssigneeIds?: string[] | null;
  currentUserId?: string | null;
  /** The chosen project's own `default_assignee`, already normalised to an id. */
  projectDefaultAssigneeId?: string | null;
  /**
   * Assignable member ids for the chosen project — `getProjectMemberIds(id, false)`,
   * whose `false` drops GUEST (role 5) and so matches the server's `role >= 15` floor.
   *
   * `null` means NOT FETCHED YET and is deliberately distinct from `[]` (fetched,
   * nobody assignable). Collapsing the two would either hide the default behind a
   * cache miss or claim a project has no members before anyone asked it.
   */
  assignableMemberIds?: string[] | null;
};

const isPresentId = (id: string | null | undefined): id is string => typeof id === "string" && id.length > 0;

/**
 * The assignee ids a create form should hold for the given project.
 *
 * Order — this is the UI half of `resolve_creation_assignee_id` in
 * plane/issue_defaults_ext/defaults.py, plus one rule the server has no reason
 * to carry: a pick the user made themselves outranks any default.
 *
 * 1. Members are not fetched yet → OPTIMISTIC. Keep whatever is selected, else
 *    the project default, else the creator. Nothing is filtered, because
 *    assignability is simply unknown; the caller re-runs this once the list
 *    lands and corrects whatever it guessed wrong.
 * 2. Otherwise, keep every currently-selected assignee who is still assignable.
 *    A partially-valid selection is NARROWED, not discarded.
 * 3. Nothing survived → the project's `default_assignee` if assignable, else the
 *    creator if assignable, else nobody.
 */
export const resolveCreationAssigneeIds = (ctx: TCreationAssigneeContext): string[] => {
  const current = (ctx.currentAssigneeIds ?? []).filter(isPresentId);
  const fallbacks = [ctx.projectDefaultAssigneeId, ctx.currentUserId].filter(isPresentId);
  const assignable = ctx.assignableMemberIds;

  if (assignable === null || assignable === undefined) {
    if (current.length > 0) return current;
    return fallbacks.length > 0 ? [fallbacks[0]] : [];
  }

  const kept = current.filter((id) => assignable.includes(id));
  if (kept.length > 0) return kept;

  const fallback = fallbacks.find((id) => assignable.includes(id));
  return fallback ? [fallback] : [];
};

/**
 * Creation-time prefill: an assignee resolved for the chosen project, due today.
 *
 * Returns an empty object when there is no candidate assignee to resolve from at
 * all — a half-hydrated user store must never produce `assignee_ids: [undefined]`,
 * and must not claim "deliberately nobody" on the user's behalf before it knows
 * who they are.
 *
 * Note the asymmetry, and keep it: `{}` means "we do not know yet", while
 * `assignee_ids: []` from a resolved context is a real answer — nobody here is
 * assignable — and must be emitted.
 *
 * The date comes from the browser's LOCAL day. The server computes its own
 * default in the creator's stored timezone for exactly this reason — a UTC
 * server and a UTC+7 browser would otherwise disagree by a day every morning.
 */
export const getWorkItemCreationDefaults = (ctx: TCreationAssigneeContext): Partial<TIssue> => {
  if (!isPresentId(ctx.currentUserId) && !isPresentId(ctx.projectDefaultAssigneeId)) return {};

  return {
    assignee_ids: resolveCreationAssigneeIds(ctx),
    target_date: renderFormattedPayloadDate(new Date()) ?? null,
  };
};
