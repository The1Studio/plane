import type { TCascadeIneligibleReason, TCascadeStateGroup } from "./types";

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
