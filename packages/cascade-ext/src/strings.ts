/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type { TCascadeIneligibleReason, TCascadeStateGroup, TModuleCascadeSummary } from "./types";

/**
 * English-only literals for the cascade confirm modal (Decision 12, plan.md). These live here,
 * not in `packages/i18n` — that's a `@plane/*` package the fork rules forbid editing in place,
 * so a key added there is lost on the next upstream bump. Localisation is a follow-up decision,
 * not made here.
 */
const TARGET_GROUP_LABEL: Record<TCascadeStateGroup, string> = {
  completed: "Completed",
  cancelled: "Cancelled",
};

// "will be completed" / "will be cancelled" — the verb form the summary sentence's first clause
// needs, distinct from `TARGET_GROUP_LABEL`'s noun form used in the description sentence above.
const TARGET_GROUP_VERB: Record<TCascadeStateGroup, string> = {
  completed: "completed",
  cancelled: "cancelled",
};

const INELIGIBLE_REASON_LABEL: Record<TCascadeIneligibleReason, string> = {
  no_matching_state: "No matching state in this project",
  no_permission: "You do not have access to this project",
};

export const CASCADE_STRINGS = {
  title: "Change sub-items too?",
  description: (parentIdentifier: string, targetGroup: TCascadeStateGroup) =>
    `${parentIdentifier} is moving to ${TARGET_GROUP_LABEL[targetGroup]}. Choose which of its sub-items should move too.`,
  // `stateName` widens to `| null` alongside `TCascadeDescendant.state_name` (types.ts) — the
  // backend's `child.state` FK is nullable (`Issue.state`, apps/api/plane/db/models/issue.py),
  // so an eligible descendant can, in principle, have no state at all.
  currentState: (stateName: string | null) => (stateName ? `Currently ${stateName}` : "No current state"),
  ineligibleReason: (reason: TCascadeIneligibleReason | null) =>
    reason ? INELIGIBLE_REASON_LABEL[reason] : "Not eligible",
  rowCheckboxLabel: (identifier: string) => `Change ${identifier} too`,
  onlyParentButton: "Only change this item",
  cascadeButton: "Change sub-items too",
} as const;

/**
 * Module-subject strings (plan.md M3 — same modal, a summary header + collapsible list added on
 * top). Kept as a sibling export rather than folded into `CASCADE_STRINGS` so an issue-subject
 * render never has to reason about module-only keys.
 */
export const MODULE_CASCADE_STRINGS = {
  title: "Change work items too?",
  description: (moduleName: string, targetGroup: TCascadeStateGroup) =>
    `"${moduleName}" is moving to ${TARGET_GROUP_LABEL[targetGroup]}. Choose which of its work items should move too.`,
  /**
   * The summary header sentence — e.g. "47 work items will be completed · 12 already done ·
   * 3 you cannot change." A zero-valued clause is OMITTED, never rendered as "0 already done"
   * (phase-2 § Implementation). "Already done" counts terminal items the walk actually reached —
   * NOT a total of everything skipped, since a pruned branch's contents are never visited (M8).
   */
  summary: (summary: TModuleCascadeSummary, targetGroup: TCascadeStateGroup): string => {
    const clauses: string[] = [];
    if (summary.eligible > 0) {
      clauses.push(
        `${summary.eligible} work item${summary.eligible === 1 ? "" : "s"} will be ${TARGET_GROUP_VERB[targetGroup]}`
      );
    }
    if (summary.already_terminal > 0) {
      clauses.push(`${summary.already_terminal} already done`);
    }
    if (summary.ineligible > 0) {
      clauses.push(`${summary.ineligible} you cannot change`);
    }
    return clauses.join(" · ");
  },
  /** Refusal-mode body (M4) — no list is ever rendered above the cap, so the real total and the
   *  cap are stated in prose instead. The module's own status write is unaffected by the refusal. */
  overCapBody: (totalLive: number, cap: number) =>
    `This module has ${totalLive} work items — more than the ${cap} this action can change at once. The module's status will still change.`,
  onlyModuleButton: "Only change this module",
  cascadeModuleButton: "Change work items too",
} as const;

/**
 * Subject-agnostic list-control strings — the collapsible list (`LIST_COLLAPSE_THRESHOLD`) and
 * its select-all/select-none pair apply the same way whether the modal is showing an issue's
 * sub-items or a module's work items.
 */
export const CASCADE_LIST_CONTROL_STRINGS = {
  showAllItems: (count: number) => `Show all ${count} items`,
  showLess: "Show less",
  selectAll: "Select all",
  selectNone: "Select none",
} as const;
