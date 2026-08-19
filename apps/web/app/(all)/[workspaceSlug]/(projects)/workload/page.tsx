// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// SP2 — Workload route page (apps/web route file).
// Imported by extended.ts.
//
// The1Studio fork (workload timeline) — renders the @plane/workload-ext
// WorkloadToolbar (member / project / state filters) directly, since the
// aggregate table it used to render internally is deleted (D11); the swimlane
// timeline lives in apps/web (D13, packages/workload-ext cannot import
// @/components/gantt-chart) and is rendered as its own sibling below it.
//
// There is no date-range control and no fetch on mount: the timeline's viewport
// is the range, and it loads what it shows (WorkloadTimelineRoot).

"use client";
import { useCallback, useEffect, useRef } from "react";
import { observer } from "mobx-react";
import { useParams } from "react-router";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { wlt, WorkloadToolbar } from "@plane/workload-ext";
import { PageHead } from "@/components/core/page-title";
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { StateGroupDropdown } from "@/components/workload/StateGroupDropdown";
import { WorkloadTimelineRoot } from "@/components/workload/timeline";
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useUserPermissions } from "@/hooks/store/user";
import { useWorkload } from "@/hooks/store/use-workload";

export default observer(function WorkloadPage() {
  const { workspaceSlug = "" } = useParams();
  const workloadStore = useWorkload();
  const { allowPermissions } = useUserPermissions();
  const { peekIssue } = useIssueDetail();
  // Capacity editing is admin-only (docs/FORK.md workload-capacity plan D-B3); workspace-scoped.
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  // No initial fetch here. The timeline loads whatever its viewport shows
  // (WorkloadTimelineRoot's viewport sync), so a fixed window fetched on mount
  // would either duplicate that request or fight it.

  // The peek panel can change start date, target date, assignee and state —
  // every field this view aggregates — so on close the range cache is dropped
  // and the timeline reloads whatever is on screen. Invalidating on close,
  // rather than diffing what changed, keeps this to one reload per edit
  // session and needs no knowledge of the panel's internals.
  const hadPeekRef = useRef(false);
  useEffect(() => {
    const isOpen = Boolean(peekIssue);
    if (hadPeekRef.current && !isOpen && workspaceSlug) workloadStore.resetCoverage();
    hadPeekRef.current = isOpen;
  }, [peekIssue, workloadStore, workspaceSlug]);

  const handleMemberChange = useCallback(
    (ids: string[]) => {
      workloadStore.setAssigneeIds(ids);
    },
    [workloadStore]
  );

  const handleProjectChange = useCallback(
    (ids: string[]) => {
      workloadStore.setProjectIds(ids);
    },
    [workloadStore]
  );

  // Same setter the state-group chips used to call. An EMPTY selection means
  // no filtering at all, not "show nothing" — the server treats an absent
  // state_groups param as every group (workload/service.py `_base_queryset`).
  const handleStateGroupChange = useCallback(
    (keys: string[]) => {
      workloadStore.setStateGroups(keys);
    },
    [workloadStore]
  );

  return (
    <>
      <PageHead title="Workload" />
      <div className="flex h-full flex-col gap-4 overflow-y-auto px-6 py-4">
        <WorkloadToolbar
          store={workloadStore}
          workspaceSlug={workspaceSlug}
          isAdmin={isAdmin}
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
          stateFilterSlot={
            <StateGroupDropdown
              value={workloadStore.selectedStateGroups}
              onChange={handleStateGroupChange}
              buttonVariant="border-with-text"
              placeholder={wlt("filters.state_groups")}
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
