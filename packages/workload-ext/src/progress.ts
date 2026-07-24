/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * Fork-owned progress semantics for the SP2 workload feature.
 *
 * Progress is displayed as a bar + % on every work item, matching the source
 * (ClickUp) "progress" column. Two sources, unified into one 0..1 fraction:
 *
 *  - PARENT tasks  → the hours-weighted rollup already computed server-side
 *    (`TWorkloadRollup.percent`, done-leaf-hours / total-leaf-hours). Null
 *    when the parent has 0 estimated hours.
 *  - LEAF tasks    → derived client-side from the work item's workflow STATE
 *    GROUP (no backend, no stored field): the state group is already in the
 *    states store. Mapping (user-locked):
 *        completed → 1.0 · started → 0.5 · unstarted → 0 · backlog → 0
 *        cancelled → null (excluded — render a dash, consistent with the
 *                          hours rollup excluding cancelled descendants)
 *
 * `null` everywhere means "no meaningful progress" → the caller renders a
 * dash, never a 0%-filled bar (0% is a real value: an un-started leaf).
 */

import type { TStateGroups } from "@plane/types";

import type { TWorkloadRollup } from "./types";

/** State-group → progress fraction (0..1), or null when excluded (cancelled). */
const LEAF_PROGRESS_BY_GROUP: Record<TStateGroups, number | null> = {
  completed: 1,
  started: 0.5,
  unstarted: 0,
  backlog: 0,
  cancelled: null,
};

/**
 * Progress fraction (0..1) for a LEAF work item from its state group, or null
 * when the group is cancelled/unknown (render a dash, not a bar).
 */
export function leafProgress(stateGroup: TStateGroups | null | undefined): number | null {
  if (!stateGroup) return null;
  const value = LEAF_PROGRESS_BY_GROUP[stateGroup];
  return value === undefined ? null : value;
}

/**
 * Unified progress fraction (0..1) for any work item.
 *
 * A non-null `rollup` is the parent signal (same convention as
 * useWorkloadEstimate): parents use the server-side hours-weighted percent;
 * everything else is a leaf and derives progress from its state group.
 *
 * Returns null when there is no meaningful progress to show (a parent with 0
 * hours, or a cancelled/stateless leaf) — the caller renders a dash.
 */
export function resolveProgress(
  rollup: TWorkloadRollup | null | undefined,
  stateGroup: TStateGroups | null | undefined
): number | null {
  if (rollup) return rollup.percent; // 0..1 or null (hours === 0)
  return leafProgress(stateGroup);
}

/** 0..1 fraction → whole-number percent for display (60 for 0.6). */
export function toProgressPercent(fraction: number): number {
  return Math.round(fraction * 100);
}
