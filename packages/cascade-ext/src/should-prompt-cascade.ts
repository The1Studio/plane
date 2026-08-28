/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type { IModule, TIssue } from "@plane/types";
import type { TCascadeStateGroup, TModuleCascadeStatus } from "./types";

const TERMINAL_GROUPS: ReadonlySet<TCascadeStateGroup> = new Set(["completed", "cancelled"]);
const TERMINAL_MODULE_STATUSES: ReadonlySet<TModuleCascadeStatus> = new Set(["completed", "cancelled"]);

export interface TShouldPromptCascadeArgs {
  data: Partial<TIssue>;
  subIssuesCount: number;
  getStateGroupById: (id: string) => string | undefined;
}

/**
 * The guard that keeps the common case free (plan.md § Flow, step 2). Returns the terminal
 * group the parent is about to enter ONLY when a `state_id` is present in `data`, that state's
 * group is one of the two terminal groups, AND the issue actually has sub-issues. Otherwise
 * `null` — no preview request, no modal.
 *
 * This runs before any network call and must stay synchronous and cheap: a Done click on a
 * leaf — the overwhelmingly common case — must cost exactly zero extra requests.
 *
 * Resolved by GROUP, never by state NAME. States are renameable per project (Decision 7 / issue
 * #54's own report), so comparing against a literal state label is exactly the bug this feature
 * exists to avoid reintroducing — `getStateGroupById` is the only source of truth here.
 */
export function shouldPromptCascade(args: TShouldPromptCascadeArgs): TCascadeStateGroup | null {
  const { data, subIssuesCount, getStateGroupById } = args;
  if (subIssuesCount <= 0) return null;
  if (!data.state_id) return null;
  const group = getStateGroupById(data.state_id);
  if (!group) return null;
  if (!TERMINAL_GROUPS.has(group as TCascadeStateGroup)) return null;
  return group as TCascadeStateGroup;
}

export interface TShouldPromptModuleCascadeArgs {
  data: Partial<IModule>;
  totalIssues: number;
}

/**
 * The module-side guard (plan.md § Flow, step 2; decision M6). Returns the module status the
 * module is about to enter ONLY when `data.status` is present and is one of the two terminal
 * statuses, AND the module has at least one work item. Otherwise `null` — no preview request,
 * no modal.
 *
 * A payload that does not carry `status` at all (a name-only edit, or any other field-only PATCH
 * on an already-completed/cancelled module) returns `null` — this is what keeps that case from
 * firing a preview request on every save (plan risk row "Modal fires on the create/update
 * modal's whole-object save").
 *
 * Deliberately does NOT subtract `completed_issues` / `cancelled_issues` from `total_issues` to
 * build a cheaper "does this module actually have live work" guard. Those three counts on
 * `IModule` cover DIRECT module members only (`packages/types/src/module/modules.ts`), while the
 * cascade walks every member's full descendant subtree (M2) — a module whose members are all
 * terminal but whose sub-items are still live would be wrongly skipped by that arithmetic. The
 * per-issue flow can afford a cheap client-side skip because a Done click is high-frequency; a
 * module status change is not (M6), so this guard pays for one request on the rare action instead
 * of re-deriving a rule only the server can get right. Do not "optimize" this back — see M6.
 */
export function shouldPromptModuleCascade(args: TShouldPromptModuleCascadeArgs): TModuleCascadeStatus | null {
  const { data, totalIssues } = args;
  if (!data.status) return null;
  if (!TERMINAL_MODULE_STATUSES.has(data.status as TModuleCascadeStatus)) return null;
  if (totalIssues <= 0) return null;
  return data.status as TModuleCascadeStatus;
}
