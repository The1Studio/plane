/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useEffect } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { ISSUE_DISPLAY_FILTERS_BY_PAGE } from "@plane/constants";
import { EIssuesStoreType, EIssueLayoutTypes } from "@plane/types";
// components
// The1Studio fork (profile-layouts) — Calendar / Spreadsheet / Gantt roots added alongside the
// upstream List and Board roots.
import { ProfileIssuesCalendarLayout } from "@/components/issues/issue-layouts/calendar/roots/profile-issues-root";
import { ProfileIssuesGanttLayout } from "@/components/issues/issue-layouts/gantt/roots/profile-issues-root";
import { ProfileIssuesKanBanLayout } from "@/components/issues/issue-layouts/kanban/roots/profile-issues-root";
import { ProfileIssuesListLayout } from "@/components/issues/issue-layouts/list/roots/profile-issues-root";
import { ProfileIssuesSpreadsheetLayout } from "@/components/issues/issue-layouts/spreadsheet/roots/profile-issues-root";
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { WorkspaceLevelWorkItemFiltersHOC } from "@/components/work-item-filters/filters-hoc/workspace-level";
import { WorkItemFiltersRow } from "@/components/work-item-filters/filters-row";
// hooks
import { useIssues } from "@/hooks/store/use-issues";
import { IssuesStoreContext } from "@/hooks/use-issue-layout-store";

type Props = {
  type: "assigned" | "subscribed" | "created";
};

/**
 * The1Studio fork (profile-layouts) — replaces a hardcoded list/kanban ternary. An unhandled
 * layout renders blank rather than throwing, so a stale persisted display-filter cannot break
 * the page. Layout availability is declared once in PROFILE_VIEW_LAYOUTS (@plane/views-ext),
 * which drives the switcher; this switch only needs to cover what that array can produce.
 */
function ProfileActiveLayout({ activeLayout }: { activeLayout: EIssueLayoutTypes | undefined }) {
  switch (activeLayout) {
    case EIssueLayoutTypes.LIST:
      return <ProfileIssuesListLayout />;
    case EIssueLayoutTypes.KANBAN:
      return <ProfileIssuesKanBanLayout />;
    case EIssueLayoutTypes.CALENDAR:
      return <ProfileIssuesCalendarLayout />;
    case EIssueLayoutTypes.SPREADSHEET:
      return <ProfileIssuesSpreadsheetLayout />;
    case EIssueLayoutTypes.GANTT:
      return <ProfileIssuesGanttLayout />;
    default:
      return null;
  }
}

export const ProfileIssuesPage = observer(function ProfileIssuesPage(props: Props) {
  const { type } = props;
  const { workspaceSlug, userId } = useParams();
  // store hooks
  const {
    issues: { setViewId },
    issuesFilter: { issueFilters, fetchFilters, updateFilterExpression },
  } = useIssues(EIssuesStoreType.PROFILE);
  // derived values
  const activeLayout = issueFilters?.displayFilters?.layout || undefined;

  useEffect(() => {
    if (setViewId) setViewId(type);
  }, [type, setViewId]);

  useSWR(
    workspaceSlug && userId ? `CURRENT_WORKSPACE_PROFILE_ISSUES_${workspaceSlug}_${userId}` : null,
    async () => {
      if (workspaceSlug && userId) {
        await fetchFilters(workspaceSlug, userId);
      }
    },
    { revalidateIfStale: false, revalidateOnFocus: false }
  );

  return (
    <IssuesStoreContext.Provider value={EIssuesStoreType.PROFILE}>
      <WorkspaceLevelWorkItemFiltersHOC
        entityId={userId}
        entityType={EIssuesStoreType.PROFILE}
        filtersToShowByLayout={ISSUE_DISPLAY_FILTERS_BY_PAGE.profile_issues.filters}
        initialWorkItemFilters={issueFilters}
        updateFilters={updateFilterExpression.bind(updateFilterExpression, workspaceSlug, userId)}
        workspaceSlug={workspaceSlug}
      >
        {({ filter: profileWorkItemsFilter }) => (
          <>
            <div className="flex h-full w-full flex-col">
              {profileWorkItemsFilter && <WorkItemFiltersRow filter={profileWorkItemsFilter} />}
              <div className="relative h-full w-full overflow-auto">
                <ProfileActiveLayout activeLayout={activeLayout} />
              </div>
            </div>
            {/* peek overview */}
            <IssuePeekOverview />
          </>
        )}
      </WorkspaceLevelWorkItemFiltersHOC>
    </IssuesStoreContext.Provider>
  );
});
