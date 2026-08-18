// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — capacity heat-cell color
// thresholds: under capacity → success, at capacity → warning, over → danger.
// Mirrors the deleted aggregate table's existing `isOver` treatment (bg-warning-subtle) but
// adds the "at capacity" and "under, but non-zero" tiers the flat table never
// needed (a table cell just showed the raw number).

/**
 * `hours` — this cell's logged hours (`row.buckets[period] ?? 0`).
 * `capacity` — this cell's capacity reference (`row.capacity_buckets[period] ?? 0`).
 * `isOver` — the API's own per-period `row.over[period]` flag (source of truth
 *   for "over", since it's computed server-side against the exact same
 *   capacity value — never re-derived from `hours > capacity` here).
 */
export function heatCellColorClass(hours: number, capacity: number, isOver: boolean): string {
  if (isOver) return "bg-danger-subtle text-danger-primary";
  if (capacity > 0 && hours >= capacity) return "bg-warning-subtle text-warning-primary";
  if (hours > 0) return "bg-success-subtle text-success-primary";
  return "text-placeholder";
}
