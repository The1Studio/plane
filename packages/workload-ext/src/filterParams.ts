/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
/**
 * The1Studio fork (SP2 workload timeline) — fork-owned.
 * Listed in docs/FORK.md "Frontend core-edit exceptions" alongside the rest of
 * `packages/workload-ext`.
 */

/**
 * URL <-> toolbar-filter translation for the workload board.
 *
 * The board's three filters (members / projects / status) lived only on the
 * singleton `WorkloadStore`, so a full page load dropped them and the reader
 * had to re-pick every one (The1Studio/plane#55).
 *
 * The URL carries them, not `localStorage`: it makes a filtered board
 * shareable and bookmarkable — which answers the report's "another device or
 * session" case for free — and leaves no stale key to migrate later.
 *
 * The param names and their comma-joined encoding are deliberately the SAME
 * ones `WorkloadService._buildParams` already puts on the wire, so what the
 * address bar shows and what the request carries cannot drift.
 */
import { STATE_GROUPS } from "@plane/constants";

export type TWorkloadFilterSelection = {
  projectIds: string[];
  assigneeIds: string[];
  stateGroups: string[];
};

/** Selection field -> search-param name. Mirrors `_buildParams` (service.ts). */
export const WORKLOAD_FILTER_PARAMS: Record<keyof TWorkloadFilterSelection, string> = {
  projectIds: "project_ids",
  assigneeIds: "assignee_ids",
  stateGroups: "state_group",
};

const VALID_STATE_GROUPS = new Set<string>(Object.keys(STATE_GROUPS));

/** One comma-joined param -> trimmed, de-duplicated, non-empty values, in order. */
function readList(search: URLSearchParams, key: string): string[] {
  const raw = search.get(key);
  if (!raw) return [];
  const seen = new Set<string>();
  for (const part of raw.split(",")) {
    const value = part.trim();
    if (value !== "") seen.add(value);
  }
  return Array.from(seen);
}

/**
 * Reads a filter selection out of the current search params. A missing or
 * empty param reads as "no filtering", never as "show nothing".
 */
export function parseWorkloadFilterParams(search: URLSearchParams): TWorkloadFilterSelection {
  return {
    projectIds: readList(search, WORKLOAD_FILTER_PARAMS.projectIds),
    assigneeIds: readList(search, WORKLOAD_FILTER_PARAMS.assigneeIds),
    // Unknown group keys are DROPPED rather than passed through. The server
    // would filter to nothing while `StateGroupDropdown` falls back to its
    // placeholder, so the toolbar would claim "no filter" for one the reader
    // can neither see nor clear — the exact failure `_base_queryset`'s own
    // comment calls out (apps/api/plane/workload/service.py).
    stateGroups: readList(search, WORKLOAD_FILTER_PARAMS.stateGroups).filter((group) => VALID_STATE_GROUPS.has(group)),
  };
}

/**
 * Returns a copy of `search` with the patched filters written back. Fields the
 * patch omits are left as they are, and every unrelated param is preserved —
 * this must never be the thing that eats a peek-panel or debug param.
 *
 * An EMPTY selection removes its param entirely instead of writing
 * `?project_ids=`, matching how the server reads an absent param: no filter at
 * all, rather than a filter that matches nothing.
 */
export function writeWorkloadFilterParams(
  search: URLSearchParams,
  patch: Partial<TWorkloadFilterSelection>
): URLSearchParams {
  const next = new URLSearchParams(search);
  for (const field of Object.keys(WORKLOAD_FILTER_PARAMS) as (keyof TWorkloadFilterSelection)[]) {
    const value = patch[field];
    if (!value) continue;
    const key = WORKLOAD_FILTER_PARAMS[field];
    if (value.length === 0) next.delete(key);
    else next.set(key, value.join(","));
  }
  return next;
}
