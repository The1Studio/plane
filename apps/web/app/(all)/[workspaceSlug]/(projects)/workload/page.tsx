// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// SP2 — Workload route page (apps/web route file).
// Imported by extended.ts.
//
// The1Studio fork (workload timeline, phase-8.md) — renders the @plane/workload-ext
// WorkloadToolbar (filters/granularity, kept as-is) directly, since the aggregate
// table it used to render internally is deleted (D11); the swimlane timeline
// lives in apps/web (D13, packages/workload-ext cannot import
// @/components/gantt-chart) and is rendered as its own sibling below the toolbar.

"use client";
import { useCallback, useEffect, useRef } from "react";
import { observer } from "mobx-react";
import { useParams } from "react-router";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import type { DateRange } from "@plane/propel/calendar";
// No `maxDate` is passed to the picker on purpose: it would clamp the whole
// calendar relative to the CURRENT `from`, making it impossible to move the
// window forward. `clampDateRange` enforces the span cap after selection instead.
import { clampDateRange, wlt, WorkloadToolbar } from "@plane/workload-ext";
import { PageHead } from "@/components/core/page-title";
import { DateRangeDropdown } from "@/components/dropdowns/date-range";
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { WorkloadTimelineRoot } from "@/components/workload/timeline";
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
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
  const { peekIssue } = useIssueDetail();
  // Capacity editing is admin-only (docs/FORK.md workload-capacity plan D-B3); workspace-scoped.
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  // Initial load. Deliberately an effect, not a render-phase call: the previous
  // `if (!data && !isLoading && !error) fetch()` guard fired during render AND
  // latched permanently once `error` was set, so no filter change could ever
  // recover the page from a single failed request.
  useEffect(() => {
    if (workspaceSlug) workloadStore.fetchWorkload(workspaceSlug);
  }, [workloadStore, workspaceSlug]);

  // Refetch once when the peek panel closes. The panel can change start date,
  // target date, assignee and state — every field this view aggregates — so a
  // board left as-is would be quietly stale. Refetching on close rather than
  // diffing what changed keeps this to one request per edit session and needs
  // no knowledge of the panel's internals.
  const hadPeekRef = useRef(false);
  useEffect(() => {
    const isOpen = Boolean(peekIssue);
    if (hadPeekRef.current && !isOpen && workspaceSlug) workloadStore.fetchWorkload(workspaceSlug);
    hadPeekRef.current = isOpen;
  }, [peekIssue, workloadStore, workspaceSlug]);

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
      <div className="flex h-full flex-col gap-4 overflow-y-auto px-6 py-4">
        <h1 className="text-xl font-semibold">Workload</h1>
        <WorkloadToolbar
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
        <WorkloadTimelineRoot store={workloadStore} workspaceSlug={workspaceSlug} />
      </div>
      {/* Peek is not global — every layout that supports it mounts its own
          (cf. issue-layouts/roots/all-issue-layout-root.tsx). It self-fetches
          the work item, so nothing has to be preloaded into an issue store. */}
      <IssuePeekOverview />
    </>
  );
});
