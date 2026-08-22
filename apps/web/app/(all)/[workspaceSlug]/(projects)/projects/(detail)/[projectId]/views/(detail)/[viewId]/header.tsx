/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { debounce } from "lodash-es";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";

// plane imports
import {
  EIssueFilterType,
  ISSUE_DISPLAY_FILTERS_BY_PAGE,
  EUserPermissions,
  EUserPermissionsLevel,
  WORK_ITEM_TRACKER_ELEMENTS,
} from "@plane/constants";
import { Button } from "@plane/propel/button";
import { LockIcon, ViewsIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import type { ICustomSearchSelectOption, IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
import { EIssuesStoreType, EViewAccess, EIssueLayoutTypes } from "@plane/types";
import { Breadcrumbs, Header, BreadcrumbNavigationSearchDropdown } from "@plane/ui";
// The1Studio fork (views-search) — `WorkItemSearchInput` ships from the fork-owned
// `@plane/views-ext` package; core's `@plane/ui` carries no work-item search input and no
// upstream seam exists to add one (see plan.md D6 — `packages/` cannot import from
// `apps/web/core/`).
import { WorkItemSearchInput } from "@plane/views-ext";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { SwitcherIcon, SwitcherLabel } from "@/components/common/switcher-label";
import { DisplayFiltersSelection, FiltersDropdown, LayoutSelection } from "@/components/issues/issue-layouts/filters";
import { ViewQuickActions } from "@/components/views/quick-actions";
import { WorkItemFiltersToggle } from "@/components/work-item-filters/filters-toggle";
// hooks
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useIssues } from "@/hooks/store/use-issues";
import { useProject } from "@/hooks/store/use-project";
import { useProjectView } from "@/hooks/store/use-project-view";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
// The1Studio fork (views-search) — selector for the fork-owned ephemeral per-view search-term
// store (core/hooks/store/use-views-search.ts). There is no upstream seam: core has no
// per-view ephemeral search-term store at all, and the store itself cannot live in
// `@plane/views-ext` (a `packages/` file cannot read `StoreContext` — same dependency
// direction as D6 in plan.md).
import { useViewsSearch } from "@/hooks/store/use-views-search";
// plane web imports
import { CommonProjectBreadcrumbs } from "@/plane-web/components/breadcrumbs/common";

export const ProjectViewIssuesHeader = observer(function ProjectViewIssuesHeader() {
  // refs
  const parentRef = useRef(null);
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId, viewId: routerViewId } = useParams();
  const viewId = routerViewId ? routerViewId.toString() : undefined;
  // store hooks
  const {
    issuesFilter: { issueFilters, updateFilters },
    issues,
  } = useIssues(EIssuesStoreType.PROJECT_VIEW);
  // The1Studio fork (views-search) — ephemeral, per-view search-term store (plan.md D3).
  // Read-only param assembly happens in filter.store.ts `getAppliedFilters`; this header only
  // writes the term and triggers the re-fetch, it never routes through `updateFilters` (B2).
  const searchStore = useViewsSearch();
  const { toggleCreateIssueModal } = useCommandPalette();
  const { allowPermissions } = useUserPermissions();

  const { currentProjectDetails, loader } = useProject();
  const { projectViewIds, getViewById } = useProjectView();

  const activeLayout = issueFilters?.displayFilters?.layout;

  const handleLayoutChange = useCallback(
    (layout: EIssueLayoutTypes) => {
      if (!workspaceSlug || !projectId || !viewId) return;
      updateFilters(
        workspaceSlug.toString(),
        projectId.toString(),
        EIssueFilterType.DISPLAY_FILTERS,
        { layout: layout },
        viewId.toString()
      );
    },
    [workspaceSlug, projectId, viewId, updateFilters]
  );

  const handleDisplayFilters = useCallback(
    (updatedDisplayFilter: Partial<IIssueDisplayFilterOptions>) => {
      if (!workspaceSlug || !projectId || !viewId) return;
      updateFilters(
        workspaceSlug.toString(),
        projectId.toString(),
        EIssueFilterType.DISPLAY_FILTERS,
        updatedDisplayFilter,
        viewId.toString()
      );
    },
    [workspaceSlug, projectId, viewId, updateFilters]
  );

  const handleDisplayProperties = useCallback(
    (property: Partial<IIssueDisplayProperties>) => {
      if (!workspaceSlug || !projectId || !viewId) return;
      updateFilters(
        workspaceSlug.toString(),
        projectId.toString(),
        EIssueFilterType.DISPLAY_PROPERTIES,
        property,
        viewId.toString()
      );
    },
    [workspaceSlug, projectId, viewId, updateFilters]
  );

  const viewDetails = viewId ? getViewById(viewId.toString()) : null;

  // The1Studio fork (views-search) — the search term for the view currently on screen. The
  // store's key is opaque; the composite `"<EIssuesStoreType>:<entityId>"` keeps a project
  // view term from ever colliding with a module/cycle/id that happens to share its id.
  // Switching views never shows a stale term (plan.md D3).
  const searchQuery = viewId ? searchStore.getSearchQuery(`${EIssuesStoreType.PROJECT_VIEW}:${viewId}`) : "";

  // The1Studio fork (views-search) — 300ms debounce (deliberately shorter than the 800ms
  // write-debounce in use-workload-estimate-editor.ts: that one guards a server WRITE, this one
  // guards a read). `fetchIssuesWithExistingPagination` is the same re-fetch path a filter
  // change takes (project-views/filter.store.ts `updateFilters`), which keeps cursor handling,
  // grouped pagination and loader states consistent with a filter change. `issues` is a stable
  // mobx store instance for the lifetime of this component, so the debounced wrapper is safe to
  // create once.
  const debouncedRefetchIssues = useMemo(
    () =>
      debounce((workspaceSlugParam: string, projectIdParam: string, viewIdParam: string) => {
        issues.fetchIssuesWithExistingPagination(workspaceSlugParam, projectIdParam, viewIdParam, "mutation");
      }, 300),
    [issues]
  );

  // The1Studio fork (views-search) — cancel the pending debounce on unmount so a term typed
  // and navigated away from within 300ms never fires a fetch against a store that just left.
  useEffect(() => () => debouncedRefetchIssues.cancel(), [debouncedRefetchIssues]);

  // The1Studio fork (views-search) — writes the term immediately (controlled input, no input
  // lag) and schedules the debounced re-fetch. Refetches on transition-to-empty too, so
  // clearing the box restores the unfiltered list. Not gated on `!viewDetails.is_locked`:
  // search never mutates what the view IS (unlike the layout switcher / display dropdown below,
  // which are hidden when locked), and it stays gated on the view id exactly like
  // `WorkItemFiltersToggle` below.
  const updateSearchQuery = useCallback(
    (query: string) => {
      if (!viewId) return;
      searchStore.setSearchQuery(`${EIssuesStoreType.PROJECT_VIEW}:${viewId}`, query);
      if (!workspaceSlug || !projectId) return;
      debouncedRefetchIssues(workspaceSlug.toString(), projectId.toString(), viewId);
    },
    [viewId, workspaceSlug, projectId, searchStore, debouncedRefetchIssues]
  );

  const canUserCreateIssue = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT
  );

  if (!viewDetails) return;

  const switcherOptions = projectViewIds
    ?.map((id) => {
      const _view = id === viewId ? viewDetails : getViewById(id);
      if (!_view) return;
      return {
        value: _view.id,
        query: _view.name,
        content: <SwitcherLabel logo_props={_view.logo_props} name={_view.name} LabelIcon={ViewsIcon} />,
      };
    })
    .filter((option) => option !== undefined) as ICustomSearchSelectOption[];

  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs isLoading={loader === "init-loader"}>
          <CommonProjectBreadcrumbs workspaceSlug={workspaceSlug?.toString()} projectId={projectId?.toString()} />
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label="Views"
                href={`/${workspaceSlug}/projects/${projectId}/views/`}
                icon={<ViewsIcon className="h-4 w-4 text-tertiary" />}
              />
            }
          />
          <Breadcrumbs.Item
            component={
              <BreadcrumbNavigationSearchDropdown
                selectedItem={viewId?.toString() ?? ""}
                navigationItems={switcherOptions}
                onChange={(value: string) => {
                  router.push(`/${workspaceSlug}/projects/${projectId}/views/${value}`);
                }}
                title={viewDetails?.name}
                icon={
                  <Breadcrumbs.Icon>
                    <SwitcherIcon logo_props={viewDetails.logo_props} LabelIcon={ViewsIcon} size={16} />
                  </Breadcrumbs.Icon>
                }
                isLast
              />
            }
          />
        </Breadcrumbs>

        {viewDetails?.access === EViewAccess.PRIVATE ? (
          <div className="cursor-default text-tertiary">
            <Tooltip tooltipContent={"Private"}>
              <LockIcon className="h-4 w-4" />
            </Tooltip>
          </div>
        ) : (
          <></>
        )}
      </Header.LeftItem>
      <Header.RightItem className="items-center">
        <>
          {/* The1Studio fork (views-search) — placed first so reading order is search → layout
              → filters → display → create. Gated on viewId only, NOT `!viewDetails.is_locked`:
              a locked view forbids changing what the view IS, and an ephemeral search term
              changes nothing about the view. Same gating as `WorkItemFiltersToggle` below. */}
          {viewId && <WorkItemSearchInput searchQuery={searchQuery} updateSearchQuery={updateSearchQuery} />}
          {!viewDetails.is_locked && (
            <LayoutSelection
              layouts={[
                EIssueLayoutTypes.LIST,
                EIssueLayoutTypes.KANBAN,
                EIssueLayoutTypes.CALENDAR,
                EIssueLayoutTypes.SPREADSHEET,
                EIssueLayoutTypes.GANTT,
              ]}
              onChange={(layout) => handleLayoutChange(layout)}
              selectedLayout={activeLayout}
            />
          )}
          {viewId && <WorkItemFiltersToggle entityType={EIssuesStoreType.PROJECT_VIEW} entityId={viewId} />}
          {!viewDetails.is_locked && (
            <FiltersDropdown title="Display" placement="bottom-end">
              <DisplayFiltersSelection
                layoutDisplayFiltersOptions={
                  activeLayout ? ISSUE_DISPLAY_FILTERS_BY_PAGE.issues.layoutOptions[activeLayout] : undefined
                }
                displayFilters={issueFilters?.displayFilters ?? {}}
                handleDisplayFiltersUpdate={handleDisplayFilters}
                displayProperties={issueFilters?.displayProperties ?? {}}
                handleDisplayPropertiesUpdate={handleDisplayProperties}
                cycleViewDisabled={!currentProjectDetails?.cycle_view}
                moduleViewDisabled={!currentProjectDetails?.module_view}
              />
            </FiltersDropdown>
          )}
        </>
        {canUserCreateIssue && (
          <Button
            variant="primary"
            size="lg"
            onClick={() => {
              toggleCreateIssueModal(true, EIssuesStoreType.PROJECT_VIEW);
            }}
            data-ph-element={WORK_ITEM_TRACKER_ELEMENTS.HEADER_ADD_BUTTON.PROJECT_VIEW}
          >
            Add work item
          </Button>
        )}
        <div className="hidden md:block">
          <ViewQuickActions
            parentRef={parentRef}
            customClassName="flex-shrink-0 flex items-center justify-center size-[26px] bg-layer-1/70 rounded-sm"
            projectId={projectId.toString()}
            view={viewDetails}
            workspaceSlug={workspaceSlug.toString()}
          />
        </div>
      </Header.RightItem>
    </Header>
  );
});
