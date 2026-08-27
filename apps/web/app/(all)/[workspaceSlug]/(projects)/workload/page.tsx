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
import { useParams, useSearchParams } from "react-router";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import type { TWorkloadFilterSelection } from "@plane/workload-ext";
import { parseWorkloadFilterParams, wlt, WorkloadToolbar, writeWorkloadFilterParams } from "@plane/workload-ext";
import { PageHead } from "@/components/core/page-title";
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { StateGroupDropdown } from "@/components/workload/StateGroupDropdown";
import { WorkloadTimelineRoot } from "@/components/workload/timeline";
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useUserPermissions } from "@/hooks/store/user";
import { useWorkload } from "@/hooks/store/use-workload";

/** Order-sensitive compare — the selections are read back in the order they were written. */
function sameSelection(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

export default observer(function WorkloadPage() {
  const { workspaceSlug = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const workloadStore = useWorkload();
  const { allowPermissions } = useUserPermissions();
  const { peekIssue } = useIssueDetail();
  // Capacity editing is admin-only (docs/FORK.md workload-capacity plan D-B3); workspace-scoped.
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  // No initial fetch here. The timeline loads whatever its viewport shows
  // (WorkloadTimelineRoot's viewport sync), so a fixed window fetched on mount
  // would either duplicate that request or fight it.

  // Workspace-switch invalidation deliberately does NOT live here as a
  // `useEffect` keyed on `workspaceSlug` — an earlier attempt at that shape
  // shipped and turned out not to fire: `workloadStore` is a SINGLETON
  // (`useWorkload`'s own doc comment) that outlives this component, but the
  // component itself does not reliably outlive a workspace switch — Plane's
  // workspace switcher can navigate through an intermediate route (e.g. back
  // to the dashboard) rather than staying on this page, unmounting and later
  // remounting `WorkloadPage` fresh. A `useRef` seeded from `workspaceSlug`
  // on that fresh mount starts already EQUAL to the current value, so a
  // "did the prop change" comparison never fires, even though the singleton
  // store underneath is still holding the previous workspace's data. The fix
  // is now in `WorkloadStore.ensureRange` itself (`packages/workload-ext`),
  // which self-invalidates on every call regardless of which component, or
  // how many mounts, triggered it — see that method's own comment.

  // The peek panel can change start date, target date, assignee and state —
  // every field this view aggregates — so on close the range cache is dropped
  // and the viewport refetches. Invalidating on close, rather than diffing
  // what changed, keeps this to one refetch per edit session and needs no
  // knowledge of the panel's internals. `invalidateCoverage` (not
  // `resetCoverage`): the drag path already established that a viewport
  // refetch should fold in on top of what is on screen rather than blanking
  // the board first — closing the peek panel is the same "may be stale,
  // reconcile quietly" case, not a filter change that makes the cache
  // describe a different query outright.
  const hadPeekRef = useRef(false);
  useEffect(() => {
    const isOpen = Boolean(peekIssue);
    if (hadPeekRef.current && !isOpen && workspaceSlug) workloadStore.invalidateCoverage();
    hadPeekRef.current = isOpen;
  }, [peekIssue, workloadStore, workspaceSlug]);

  // ── Filter persistence (The1Studio/plane#55) ───────────────────────────────
  // The filters live on a SINGLETON store with no persistence of its own, so
  // before this every reload dropped them and the reader re-picked all three.
  // They are mirrored into the URL rather than localStorage: a filtered board
  // is then shareable and bookmarkable, which is the report's "another device
  // or session" case, and there is no stale key to migrate later. Encoding is
  // `packages/workload-ext/src/filterParams.ts` — the same param names the
  // request already carries.

  const applyFilterParams = useCallback(
    (patch: Partial<TWorkloadFilterSelection>) => {
      // `replace`, not push: a filter change is a change of view, not a
      // destination, and pushing would make Back walk every dropdown click.
      setSearchParams((prev) => writeWorkloadFilterParams(prev, patch), { replace: true });
    },
    [setSearchParams]
  );

  // Seeds the store from the URL once per workspace. The ref starts `null`
  // rather than at the current slug, which is what makes it correct on BOTH
  // paths the comment above describes: a fresh mount (workspace switch through
  // an intermediate route) seeds because `null !== workspaceSlug`, and an
  // in-place slug change seeds because the previous slug !== the new one. It
  // is deliberately NOT the "did the prop change" comparison that failed here
  // before — that one had to DETECT a change on a fresh mount, and a ref
  // seeded from the current value never can.
  //
  // Seeding a workspace whose URL carries no filters clears whatever the
  // singleton is still holding from the previous one, so filters cannot bleed
  // across a switch. Each setter is called only when the value actually
  // differs, so the common no-filters visit costs no `resetCoverage` at all.
  const seededWorkspaceRef = useRef<string | null>(null);
  useEffect(() => {
    if (!workspaceSlug || seededWorkspaceRef.current === workspaceSlug) return;
    seededWorkspaceRef.current = workspaceSlug;
    const seeded = parseWorkloadFilterParams(searchParams);
    if (!sameSelection(seeded.projectIds, workloadStore.selectedProjectIds))
      workloadStore.setProjectIds(seeded.projectIds);
    if (!sameSelection(seeded.assigneeIds, workloadStore.selectedAssigneeIds))
      workloadStore.setAssigneeIds(seeded.assigneeIds);
    if (!sameSelection(seeded.stateGroups, workloadStore.selectedStateGroups))
      workloadStore.setStateGroups(seeded.stateGroups);
  }, [workspaceSlug, searchParams, workloadStore]);

  const handleMemberChange = useCallback(
    (ids: string[]) => {
      workloadStore.setAssigneeIds(ids);
      applyFilterParams({ assigneeIds: ids });
    },
    [workloadStore, applyFilterParams]
  );

  const handleProjectChange = useCallback(
    (ids: string[]) => {
      workloadStore.setProjectIds(ids);
      applyFilterParams({ projectIds: ids });
    },
    [workloadStore, applyFilterParams]
  );

  // Same setter the state-group chips used to call. An EMPTY selection means
  // no filtering at all, not "show nothing" — the server treats an absent
  // state_groups param as every group (workload/service.py `_base_queryset`).
  const handleStateGroupChange = useCallback(
    (keys: string[]) => {
      workloadStore.setStateGroups(keys);
      applyFilterParams({ stateGroups: keys });
    },
    [workloadStore, applyFilterParams]
  );

  // "Clear filters" empties the store inside the toolbar; this strips the
  // params it left behind. Without it the board clears and the next reload
  // restores exactly the filters that were just cleared.
  const handleFiltersCleared = useCallback(() => {
    applyFilterParams({ projectIds: [], assigneeIds: [], stateGroups: [] });
  }, [applyFilterParams]);

  return (
    <>
      <PageHead title="Workload" />
      <div className="flex h-full flex-col gap-4 overflow-y-auto px-6 py-4">
        <WorkloadToolbar
          store={workloadStore}
          workspaceSlug={workspaceSlug}
          isAdmin={isAdmin}
          onFiltersCleared={handleFiltersCleared}
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
