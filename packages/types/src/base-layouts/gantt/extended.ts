/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export const EXTENDED_GANTT_TIMELINE_TYPE = {
  /**
   * The1Studio fork (workload timeline, phase-8.md) — per-assignee swimlane
   * timeline on the workspace Workload page. Composed via `GanttChartRoot`
   * with a flat, assignee-grouped `blockIds` list built from the workload
   * API response (see `apps/web/core/components/workload/timeline/`). Uses
   * a plain `BaseTimeLineStore` instance (no autorun-driven data source of
   * its own, unlike `ISSUE`/`MODULE`) — the workload timeline root pushes
   * block data into it directly via `updateBlocks`.
   */
  WORKLOAD: "WORKLOAD",
} as const;
