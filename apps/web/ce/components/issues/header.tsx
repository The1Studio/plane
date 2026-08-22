/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo } from "react";
import { debounce } from "lodash-es";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// icons
import { Circle } from "lucide-react";
// plane imports
import {
  EUserPermissions,
  EUserPermissionsLevel,
  SPACE_BASE_PATH,
  SPACE_BASE_URL,
  WORK_ITEM_TRACKER_ELEMENTS,
} from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { NewTabIcon, WorkItemsIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import { EIssuesStoreType } from "@plane/types";
import { Breadcrumbs, Header } from "@plane/ui";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { CountChip } from "@/components/common/count-chip";
// constants
import { HeaderFilters } from "@/components/issues/filters";
// helpers
// hooks
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useIssues } from "@/hooks/store/use-issues";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
// The1Studio fork (views-search) — selector hook for the fork's in-memory `viewsSearchStore`.
// It lives under `core/hooks/store/` (not in `@plane/views-ext`) because a package under
// `packages/` cannot read `StoreContext` — same dependency-direction constraint the cycle/module
// headers document.
import { useViewsSearch } from "@/hooks/store/use-views-search";
import { useAppRouter } from "@/hooks/use-app-router";
import { usePlatformOS } from "@/hooks/use-platform-os";
// plane web imports
import { CommonProjectBreadcrumbs } from "@/plane-web/components/breadcrumbs/common";

export const IssuesHeader = observer(function IssuesHeader() {
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId } = useParams();
  // store hooks
  const { issues } = useIssues(EIssuesStoreType.PROJECT);
  const { getGroupIssueCount } = issues;
  // The1Studio fork (views-search) — ephemeral search term store. Read-only param assembly
  // happens in filter.store.ts `getAppliedFilters`; this header only writes the term and
  // triggers the re-fetch, it never routes through `updateFilters` — that path PATCHes
  // `ProjectUserProperties`, which is persisted server-side and would outlive the term's
  // intended lifetime.
  const searchStore = useViewsSearch();
  // i18n
  const { t } = useTranslation();

  const { currentProjectDetails, loader } = useProject();

  const { toggleCreateIssueModal } = useCommandPalette();
  const { allowPermissions } = useUserPermissions();
  const { isMobile } = usePlatformOS();

  const SPACE_APP_URL = (SPACE_BASE_URL.trim() === "" ? window.location.origin : SPACE_BASE_URL) + SPACE_BASE_PATH;
  const publishedURL = `${SPACE_APP_URL}/issues/${currentProjectDetails?.anchor}`;

  const issuesCount = getGroupIssueCount(undefined, undefined, false);
  const canUserCreateIssue = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT
  );

  // The1Studio fork (views-search) — the PROJECT store's search key is an opaque composite
  // `${EIssuesStoreType.PROJECT}:${projectId}` so that a project and another entity (module /
  // cycle / project view) that might share an id can never collide in `viewsSearchStore`.
  const projectSearchKey = `${EIssuesStoreType.PROJECT}:${projectId}`;

  // The1Studio fork (views-search) — the term for the project currently on screen. A missing or
  // empty term is `""` (never `undefined`) per the store contract.
  const searchQuery = searchStore.getSearchQuery(projectSearchKey);

  // The1Studio fork (views-search) — 300ms debounce (deliberately shorter than the 800ms write
  // debounce in use-workload-estimate-editor.ts: that one guards a server WRITE, this one guards
  // a read). Reuses `issues.fetchIssuesWithExistingPagination`, the same re-fetch path a filter
  // change takes (filter.store.ts:243), which keeps cursor handling, grouped pagination and
  // loader states consistent with a filter change. `issues` comes from the stable mobx store
  // instance via `useIssues`, so the debounced wrapper is safe to create once.
  const debouncedRefetchIssues = useMemo(
    () =>
      debounce((workspaceSlugParam: string, projectIdParam: string) => {
        issues.fetchIssuesWithExistingPagination(workspaceSlugParam, projectIdParam, "mutation");
      }, 300),
    [issues]
  );

  // The1Studio fork (views-search) — cancel the pending debounce on unmount so a stale term
  // change can never schedule a re-fetch for a project/page that is already gone.
  useEffect(() => () => debouncedRefetchIssues.cancel(), [debouncedRefetchIssues]);

  // The1Studio fork (views-search) — clear the term for the project being left, whether that's
  // a switch to a different project or navigating out of the Work Items tab entirely. Also fires
  // the transition-to-empty re-fetch (clearing the box restores the full list) when the term
  // being cleared actually transitioned to empty.
  useEffect(
    () => () => {
      const previousQuery = searchStore.getSearchQuery(projectSearchKey);
      if (projectId) {
        if (previousQuery !== "" && workspaceSlug)
          issues.fetchIssuesWithExistingPagination(workspaceSlug.toString(), projectId.toString(), "mutation");
        searchStore.clearSearchQuery(projectSearchKey);
      }
    },
    [projectId, projectSearchKey, workspaceSlug, issues, searchStore]
  );

  // The1Studio fork (views-search) — writes the term immediately (controlled input, no input
  // lag) and schedules the debounced re-fetch. Not gated on any permission: search never
  // mutates the project (unlike display filters), so a read-only user still searches.
  const updateSearchQuery = useCallback(
    (query: string) => {
      if (!projectId) return;
      searchStore.setSearchQuery(projectSearchKey, query);
      if (!workspaceSlug) return;
      debouncedRefetchIssues(workspaceSlug.toString(), projectId.toString());
    },
    [projectId, projectSearchKey, workspaceSlug, searchStore, debouncedRefetchIssues]
  );

  return (
    <Header>
      <Header.LeftItem>
        <div className="flex items-center gap-2.5">
          <Breadcrumbs onBack={() => router.back()} isLoading={loader === "init-loader"} className="flex-grow-0">
            <CommonProjectBreadcrumbs workspaceSlug={workspaceSlug?.toString()} projectId={projectId?.toString()} />
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink
                  label="Work Items"
                  href={`/${workspaceSlug}/projects/${projectId}/issues/`}
                  icon={<WorkItemsIcon className="h-4 w-4 text-tertiary" />}
                  isLast
                />
              }
              isLast
            />
          </Breadcrumbs>
          {issuesCount && issuesCount > 0 ? (
            <Tooltip
              isMobile={isMobile}
              tooltipContent={`There are ${issuesCount} ${issuesCount > 1 ? "work items" : "work item"} in this project`}
              position="bottom"
            >
              <CountChip count={issuesCount} />
            </Tooltip>
          ) : null}
        </div>
        {currentProjectDetails?.anchor ? (
          <a
            href={publishedURL}
            className="group flex items-center gap-1.5 rounded-sm bg-accent-primary/10 px-2.5 py-1 text-11 font-medium text-accent-primary"
            target="_blank"
            rel="noopener noreferrer"
          >
            <Circle className="h-1.5 w-1.5 fill-accent-primary" strokeWidth={2} />
            {t("workspace_projects.network.public.title")}
            <NewTabIcon className="hidden h-3 w-3 group-hover:block" strokeWidth={2} />
          </a>
        ) : (
          <></>
        )}
      </Header.LeftItem>
      <Header.RightItem>
        <div className="hidden gap-2 md:flex">
          <HeaderFilters
            projectId={projectId}
            currentProjectDetails={currentProjectDetails}
            workspaceSlug={workspaceSlug}
            canUserCreateIssue={canUserCreateIssue}
            searchQuery={searchQuery}
            updateSearchQuery={updateSearchQuery}
          />
        </div>
        {canUserCreateIssue && (
          <Button
            variant="primary"
            size="lg"
            onClick={() => {
              toggleCreateIssueModal(true, EIssuesStoreType.PROJECT);
            }}
            data-ph-element={WORK_ITEM_TRACKER_ELEMENTS.HEADER_ADD_BUTTON.WORK_ITEMS}
          >
            <div className="block sm:hidden">{t("issue.label", { count: 1 })}</div>
            <div className="hidden sm:block">{t("issue.add.label")}</div>
          </Button>
        )}
      </Header.RightItem>
    </Header>
  );
});
