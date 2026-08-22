import type { TStateGroups } from "@plane/types";

/**
 * The two terminal state groups this feature ever cascades into. Mirrors the backend
 * `cascade_ext` contract (plans/260822-cascade-complete-sub-items/phase-1-cascade-backend.md) —
 * cascade never fires for `backlog` / `unstarted` / `started` (Decision 4).
 */
export type TCascadeStateGroup = Extract<TStateGroups, "completed" | "cancelled">;

/**
 * Why a descendant row can't be moved (Decision 8) — shown disabled with this reason, never
 * hidden. `null` means the row IS eligible.
 */
export type TCascadeIneligibleReason = "no_matching_state" | "no_permission";

/**
 * One row of the cascade-preview response (phase-1 § Endpoint contract). Already-terminal
 * descendants are never present here (Decision 5) — the backend excludes them before this ever
 * reaches the client, though it still traverses through them to find their own live descendants.
 */
export interface TCascadeDescendant {
  id: string;
  identifier: string;
  name: string;
  depth: number;
  project_id: string;
  project_name: string;
  state_id: string;
  state_name: string;
  state_group: string;
  target_state_id: string;
  eligible: boolean;
  reason: TCascadeIneligibleReason | null;
}

export interface TCascadePreviewResponse {
  target_group: TCascadeStateGroup;
  depth_capped: boolean;
  descendants: TCascadeDescendant[];
}

export interface TCascadeApplyRejection {
  id: string;
  reason: string;
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
