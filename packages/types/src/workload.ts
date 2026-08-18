/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// The1Studio fork (workspace work settings) — new file.
// See plans/260818-workload-workspace-settings/phase-0.md for the shared
// contract this type mirrors (backend: apps/api/plane/workload/constants.py).

/**
 * @description Workspace-wide workload settings — replaces the per-member
 * `WorkloadCapacity` model and the per-user `start_of_the_week` preference
 * as the sole source of truth for capacity math and week bucketing.
 *
 * `workdays` and `week_start_day` use Plane's existing `EStartOfTheWeek`
 * encoding (`SUNDAY = 0` .. `SATURDAY = 6`, see `./users.ts`) — the SAME
 * numbering the backend's `to_plane_weekday()` produces, so no remapping is
 * needed at the API boundary in either direction.
 */
export type TWorkSettings = {
  /** 0 <= x <= 10000 (MAX_HOURS, apps/api/plane/workload/aggregation.py). */
  max_weekly_hours: number;
  /** Non-empty, unique, ascending EStartOfTheWeek values. */
  workdays: number[];
  /** EStartOfTheWeek value. */
  week_start_day: number;
};
