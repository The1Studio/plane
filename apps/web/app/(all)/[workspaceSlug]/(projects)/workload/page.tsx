// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// SP2 — Workload route page (apps/web route file).
// Imported by extended.ts; renders the @plane/workload-ext WorkloadMatrix.

"use client";
import { useCallback, useEffect } from "react";
import { observer } from "mobx-react";
import { useParams } from "react-router";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import type { DateRange } from "@plane/propel/calendar";
// No `maxDate` is passed to the picker on purpose: it would clamp the whole
// calendar relative to the CURRENT `from`, making it impossible to move the
// window forward. `clampDateRange` enforces the span cap after selection instead.
import { clampDateRange, wlt, WorkloadMatrix } from "@plane/workload-ext";
import { PageHead } from "@/components/core/page-title";
import { DateRangeDropdown } from "@/components/dropdowns/date-range";
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
import { useUserPermissions } from "@/hooks/store/user";
import { useWorkload } from "@/hooks/store/use-workload";

/** Parse a YYYY-MM-DD store value into a Date for the calendar dropdown. */
function toDate(value: string): Date | undefined {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/** Format a Date back into the YYYY-MM-DD the store and API speak. */
function toDateString(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default observer(function WorkloadPage() {
  const { workspaceSlug = "" } = useParams();
  const workloadStore = useWorkload();
  const { allowPermissions } = useUserPermissions();
  // Capacity editing is admin-only (docs/FORK.md workload-capacity plan D-B3); workspace-scoped.
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  // Initial load. Deliberately an effect, not a render-phase call: the previous
  // `if (!data && !isLoading && !error) fetch()` guard fired during render AND
  // latched permanently once `error` was set, so no filter change could ever
  // recover the page from a single failed request.
  useEffect(() => {
    if (workspaceSlug) workloadStore.fetchWorkload(workspaceSlug);
  }, [workloadStore, workspaceSlug]);

  const handleMemberChange = useCallback(
    (ids: string[]) => {
      workloadStore.setAssigneeIds(ids);
      workloadStore.fetchWorkload(workspaceSlug);
    },
    [workloadStore, workspaceSlug]
  );

  const handleProjectChange = useCallback(
    (ids: string[]) => {
      workloadStore.setProjectIds(ids);
      workloadStore.fetchWorkload(workspaceSlug);
    },
    [workloadStore, workspaceSlug]
  );

  const handleDateRangeSelect = useCallback(
    (range: DateRange | undefined) => {
      if (!range?.from || !range?.to) return;
      // The span clamp is owned by the package (it mirrors the API's _SPAN_CAPS);
      // the app only supplies the picker UI. `to` is the anchor because the
      // dropdown commits a range with the end date last.
      const { from, to } = clampDateRange(
        toDateString(range.from),
        toDateString(range.to),
        workloadStore.granularity,
        "to"
      );
      workloadStore.setDateRange(from, to);
      workloadStore.fetchWorkload(workspaceSlug);
    },
    [workloadStore, workspaceSlug]
  );

  return (
    <>
      <PageHead title="Workload" />
      <div className="h-full overflow-y-auto px-6 py-4">
        <h1 className="text-xl mb-4 font-semibold">Workload</h1>
        <WorkloadMatrix
          store={workloadStore}
          workspaceSlug={workspaceSlug}
          isAdmin={isAdmin}
          dateRangeSlot={
            <DateRangeDropdown
              buttonVariant="border-with-text"
              value={{ from: toDate(workloadStore.dateFrom), to: toDate(workloadStore.dateTo) }}
              onSelect={handleDateRangeSelect}
              placeholder={{ from: wlt("common.from"), to: wlt("common.to") }}
              mergeDates
            />
          }
          memberFilterSlot={
            <MemberDropdown
              multiple
              value={workloadStore.selectedAssigneeIds}
              onChange={handleMemberChange}
              buttonVariant="border-with-text"
              placeholder={wlt("filters.members")}
            />
          }
          projectFilterSlot={
            <ProjectDropdown
              multiple
              value={workloadStore.selectedProjectIds}
              onChange={handleProjectChange}
              buttonVariant="border-with-text"
              placeholder={wlt("filters.projects")}
            />
          }
        />
      </div>
    </>
  );
});
