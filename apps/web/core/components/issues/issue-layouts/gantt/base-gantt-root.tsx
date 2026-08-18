/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useCallback, useEffect } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { ALL_ISSUES, EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IBlockUpdateData, TIssue } from "@plane/types";
// The1Studio fork (views-layouts) — EIssuesStoreType needs to be a value import (not type-only)
// for the D5 `storeType === EIssuesStoreType.GLOBAL` runtime check below.
import { EIssueLayoutTypes, EIssuesStoreType, GANTT_TIMELINE_TYPE } from "@plane/types";
import { renderFormattedPayloadDate } from "@plane/utils";
// components
import { TimeLineTypeContext } from "@/components/gantt-chart/contexts";
import { GanttChartRoot } from "@/components/gantt-chart/root";
import { IssueGanttSidebar } from "@/components/gantt-chart/sidebar/issues/sidebar";
// hooks
import { useIssues } from "@/hooks/store/use-issues";
import { useUserPermissions } from "@/hooks/store/user";
import { useIssueStoreType } from "@/hooks/use-issue-layout-store";
import { useIssuesActions } from "@/hooks/use-issues-actions";
import { useTimeLineChart } from "@/hooks/use-timeline-chart";
// plane web hooks
import { useBulkOperationStatus } from "@/plane-web/hooks/use-bulk-operation-status";

import { IssueLayoutHOC } from "../issue-layout-HOC";
import { GanttQuickAddIssueButton, QuickAddIssueRoot } from "../quick-add";
import { IssueGanttBlock } from "./blocks";

interface IBaseGanttRoot {
  viewId?: string | undefined;
  isCompletedCycle?: boolean;
  isEpic?: boolean;
}

export type GanttStoreType =
  | EIssuesStoreType.PROJECT
  | EIssuesStoreType.MODULE
  | EIssuesStoreType.CYCLE
  | EIssuesStoreType.PROJECT_VIEW
  | EIssuesStoreType.EPIC
  // The1Studio fork (views-layouts) — B3/D5: workspace-wide Timeline for the Views tab. No
  // workspace-level Gantt existed upstream. See updateBlockDates below for the reason this
  // needs its own branch rather than reusing the project-scoped `updateIssueDates` path.
  | EIssuesStoreType.GLOBAL
  // The1Studio fork (profile-layouts) — the profile "Your work" pages' Timeline layout. Route
  // `/profile/:userId/assigned` has no `:projectId` either, so it hits the identical B3/D5
  // crash as GLOBAL. See `isWorkspaceLevelGanttStore` below.
  | EIssuesStoreType.PROFILE;

// The1Studio fork (profile-layouts) — generalises the original GLOBAL-only D5 check so the next
// workspace-level store added to `GanttStoreType` inherits the fallback instead of reintroducing
// the B3 crash. A "workspace-level" store here means: no `:projectId` route param, and a drag
// selection that can span multiple projects at once.
const isWorkspaceLevelGanttStore = (storeType: GanttStoreType): boolean =>
  storeType === EIssuesStoreType.GLOBAL || storeType === EIssuesStoreType.PROFILE;

export const BaseGanttRoot = observer(function BaseGanttRoot(props: IBaseGanttRoot) {
  const { viewId, isCompletedCycle = false, isEpic = false } = props;
  const { t } = useTranslation();
  // router
  const { workspaceSlug, projectId } = useParams();

  const storeType = useIssueStoreType() as GanttStoreType;
  // The1Studio fork (views-layouts) — `issueMap` is looked up for the D5 fallback below (each
  // `TIssue`'s own `project_id`, since a workspace-wide drag selection can span projects).
  const { issues, issuesFilter, issueMap } = useIssues(storeType);
  const { fetchIssues, fetchNextIssues, updateIssue, quickAddIssue } = useIssuesActions(storeType);
  const { initGantt } = useTimeLineChart(GANTT_TIMELINE_TYPE.ISSUE);
  // store hooks
  const { allowPermissions } = useUserPermissions();

  const appliedDisplayFilters = issuesFilter.issueFilters?.displayFilters;
  // plane web hooks
  const isBulkOperationsEnabled = useBulkOperationStatus();
  // derived values
  const targetDate = new Date();
  targetDate.setDate(targetDate.getDate() + 1);

  useEffect(() => {
    fetchIssues("init-loader", { canGroup: false, perPageCount: 100 }, viewId);
  }, [fetchIssues, storeType, viewId]);

  useEffect(() => {
    initGantt();
  }, []);

  const issuesIds = (issues.groupedIssueIds?.[ALL_ISSUES] as string[]) ?? [];
  const nextPageResults = issues.getPaginationData(undefined, undefined)?.nextPageResults;

  // The1Studio fork (profile-layouts) — `enableQuickAdd` added to the destructure below so the
  // quick-add gate can honour it (see the `quickAdd` ternary further down).
  const { enableIssueCreation, enableQuickAdd } = issues?.viewFlags || {};

  const loadMoreIssues = useCallback(() => {
    fetchNextIssues();
  }, [fetchNextIssues]);

  const updateIssueBlockStructure = async (issue: TIssue, data: IBlockUpdateData) => {
    if (!workspaceSlug) return;

    const payload: any = { ...data };
    if (data.sort_order) payload.sort_order = data.sort_order.newSortOrder;

    updateIssue && (await updateIssue(issue.project_id, issue.id, payload));
  };

  const isAllowed = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT);
  const updateBlockDates = useCallback(
    (
      updates: {
        id: string;
        start_date?: string;
        target_date?: string;
      }[]
    ) => {
      // The1Studio fork (views-layouts / profile-layouts) — B3/D5: `updateIssueDates` takes one
      // `projectId` for the whole batch, but a workspace-level Timeline (GLOBAL or PROFILE store)
      // can hold items from many projects in a single drag selection, so there is no correct
      // single project to pass (a real API-shape mismatch, not a missing cast — see plan.md § B3).
      // Fall back to per-item `updateIssue`, keyed by each issue's own `project_id` — the same
      // call the per-issue write above (`updateIssueBlockStructure`) already uses. Every other
      // (project-scoped) store keeps the existing bulk `updateIssueDates` call, byte-for-byte
      // unchanged.
      if (isWorkspaceLevelGanttStore(storeType)) {
        return Promise.all(
          updates.map((update) => {
            const issueProjectId = issueMap[update.id]?.project_id;
            if (!updateIssue || !issueProjectId) return Promise.resolve();
            const payload: Partial<TIssue> = {};
            if (update.start_date) payload.start_date = update.start_date;
            if (update.target_date) payload.target_date = update.target_date;
            return updateIssue(issueProjectId, update.id, payload);
          })
        )
          .then(() => undefined)
          .catch(() => {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("toast.error"),
              message: "Error while updating work item dates, Please try again Later",
            });
          });
      }

      return issues.updateIssueDates(workspaceSlug.toString(), updates, projectId.toString()).catch(() => {
        setToast({
          type: TOAST_TYPE.ERROR,
          title: t("toast.error"),
          message: "Error while updating work item dates, Please try again Later",
        });
      });
    },
    [issues, projectId, workspaceSlug, storeType, issueMap, updateIssue]
  );

  // The1Studio fork (profile-layouts) — `enableQuickAdd` added to the condition. Gantt was the
  // only one of the four base roots (list/kanban/spreadsheet all gate on both `enableQuickAdd`
  // AND `enableIssueCreation`) that ignored `enableQuickAdd` — on the PROFILE store's
  // assigned/created views, `enableIssueCreation` is `true` while `enableQuickAdd` is `false`
  // (`store/issue/profile/issue.store.ts`), so Gantt would have rendered a quick-add button wired
  // to `useProfileIssueActions`'s absent `quickAddIssue`. This aligns Gantt with its three
  // siblings rather than adding fork-specific behaviour — `ProjectIssues.viewFlags.enableQuickAdd`
  // is `true`, so project/cycle/module/project-view Gantt are unaffected, and the GLOBAL store
  // stays suppressed via its own `enableIssueCreation: false`.
  const quickAdd =
    enableQuickAdd && enableIssueCreation && isAllowed && !isCompletedCycle ? (
      <QuickAddIssueRoot
        layout={EIssueLayoutTypes.GANTT}
        QuickAddButton={GanttQuickAddIssueButton}
        containerClassName="sticky bottom-0 z-[1]"
        prePopulatedData={{
          start_date: renderFormattedPayloadDate(new Date()),
          target_date: renderFormattedPayloadDate(targetDate),
        }}
        quickAddCallback={quickAddIssue}
        isEpic={isEpic}
      />
    ) : undefined;

  return (
    <IssueLayoutHOC layout={EIssueLayoutTypes.GANTT}>
      <TimeLineTypeContext.Provider value={GANTT_TIMELINE_TYPE.ISSUE}>
        <div className="h-full w-full">
          <GanttChartRoot
            border={false}
            title={isEpic ? t("epic.label", { count: 2 }) : t("issue.label", { count: 2 })}
            loaderTitle={isEpic ? t("epic.label", { count: 2 }) : t("issue.label", { count: 2 })}
            blockIds={issuesIds}
            blockUpdateHandler={updateIssueBlockStructure}
            blockToRender={(data: TIssue) => <IssueGanttBlock issueId={data.id} isEpic={isEpic} />}
            sidebarToRender={(props) => <IssueGanttSidebar {...props} showAllBlocks isEpic={isEpic} />}
            enableBlockLeftResize={isAllowed}
            enableBlockRightResize={isAllowed}
            enableBlockMove={isAllowed}
            enableReorder={appliedDisplayFilters?.order_by === "sort_order" && isAllowed}
            enableAddBlock={isAllowed}
            enableSelection={isBulkOperationsEnabled && isAllowed}
            quickAdd={quickAdd}
            loadMoreBlocks={loadMoreIssues}
            canLoadMoreBlocks={nextPageResults}
            updateBlockDates={updateBlockDates}
            showAllBlocks
            enableDependency
            isEpic={isEpic}
          />
        </div>
      </TimeLineTypeContext.Provider>
    </IssueLayoutHOC>
  );
});
