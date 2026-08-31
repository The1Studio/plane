/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type { TModuleStatus, TStateGroups } from "@plane/types";

/**
 * The two terminal state groups this feature ever cascades into. Mirrors the backend
 * `cascade_ext` contract (plans/260822-cascade-complete-sub-items/phase-1-cascade-backend.md) —
 * cascade never fires for `backlog` / `unstarted` / `started` (Decision 4).
 */
export type TCascadeStateGroup = Extract<TStateGroups, "completed" | "cancelled">;

/** The two `Module.status` values that ever cascade (plan.md M7) — mirrors `TCascadeStateGroup`
 *  one level up, as a module status rather than a state group. */
export type TModuleCascadeStatus = Extract<TModuleStatus, "completed" | "cancelled">;

/**
 * Why a descendant row can't be moved (Decision 8) — shown disabled with this reason, never
 * hidden. `null` means the row IS eligible.
 */
export type TCascadeIneligibleReason = "no_matching_state" | "no_permission";

/**
 * One row of the cascade-preview response (phase-1 § Endpoint contract). Already-terminal
 * descendants are never present here (Decision 5) — the backend excludes them before this ever
 * reaches the client, and — since `plans/260828-module-cascade-terminal-status/` Phase 0
 * (2026-08-28) — it also PRUNES their entire subtree rather than traversing through them: nothing
 * beneath a terminal node is listed, walked, or changed by either the issue or the module cascade.
 * A live sub-item under a cancelled parent is now left live, not swept.
 */
export interface TCascadeDescendant {
  id: string;
  identifier: string;
  name: string;
  depth: number;
  project_id: string;
  project_name: string;
  /** Backend emits `null` when `child.state` is falsy (`service.py::collect_descendants`). */
  state_id: string | null;
  state_name: string | null;
  state_group: string | null;
  /** Backend emits `null` for ineligible rows — the project has no matching target state. */
  target_state_id: string | null;
  eligible: boolean;
  reason: TCascadeIneligibleReason | null;
}

export interface TCascadePreviewResponse {
  target_group: TCascadeStateGroup;
  depth_capped: boolean;
  descendants: TCascadeDescendant[];
}

/**
 * A module-cascade preview row (phase-1 § Endpoint contract) — the same node shape the issue
 * flow uses, plus whether the row is itself a direct module member (`depth: 0` can ALSO be a
 * module member that happens to be a descendant of another member, so this is emitted explicitly
 * rather than inferred from `depth === 0`).
 */
export type TCascadeItem = TCascadeDescendant & {
  is_module_member: boolean;
};

export interface TModuleCascadeSummary {
  total_live: number;
  eligible: number;
  ineligible: number;
  /** Terminal nodes the walk actually encountered — NOT a total of everything pruned behind
   *  them, which is never visited and therefore uncountable (M8 / phase-1 § Endpoint contract). */
  already_terminal: number;
}

export interface TModuleCascadePreviewResponse {
  target_group: TCascadeStateGroup;
  depth_capped: boolean;
  /** M4 — a hard refusal, not a partial result. When `true`, `items` is `[]` and `summary`
   *  alone carries the real counts; the modal renders refusal mode off `summary` + `cap`. */
  over_cap: boolean;
  cap: number;
  summary: TModuleCascadeSummary;
  items: TCascadeItem[];
}

/**
 * Reachable across BOTH the issue-apply and module-apply endpoints (`service.py::apply_cascade`
 * and `::apply_module_cascade`) — a shared type rather than two near-identical ones, so a caller
 * switching between subjects doesn't need a second exhaustiveness check. `not_a_descendant` is
 * issue-only, `not_in_module_tree` is module-only; every other member is common to both.
 */
export type TCascadeApplyRejectionReason =
  | TCascadeIneligibleReason
  | "already_terminal"
  | "under_terminal_ancestor"
  | "not_a_descendant"
  | "not_in_module_tree"
  | "not_eligible";

export interface TCascadeApplyRejection {
  id: string;
  reason: TCascadeApplyRejectionReason;
}

/**
 * `updated` is documented in phase-1's endpoint contract only as `"updated": [...]` — the shape
 * of each entry isn't pinned down there, only `rejected`'s is. Typed here as the list of child
 * ids the server actually moved, mirroring the request's own `child_ids` shape. If phase-1 lands
 * with a richer per-row object instead of bare ids, this is the one place to widen it.
 */
export interface TCascadeApplyResponse {
  parent: string;
  updated: string[];
  rejected: TCascadeApplyRejection[];
}

export interface TModuleCascadeApplyResponse {
  module: string;
  status: TModuleCascadeStatus;
  updated: string[];
  rejected: TCascadeApplyRejection[];
}
