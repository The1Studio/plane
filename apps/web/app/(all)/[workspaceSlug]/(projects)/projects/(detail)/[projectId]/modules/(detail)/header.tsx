/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { debounce } from "lodash-es";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// icons
import { ChartNoAxesColumn, PanelRight, SlidersHorizontal } from "lucide-react";
// plane imports
import {
  EIssueFilterType,
  ISSUE_DISPLAY_FILTERS_BY_PAGE,
  EUserPermissions,
  EUserPermissionsLevel,
  WORK_ITEM_TRACKER_ELEMENTS,
} from "@plane/constants";
import { Button } from "@plane/propel/button";
import { ModuleIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import type { ICustomSearchSelectOption, IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
import { EIssuesStoreType, EIssueLayoutTypes } from "@plane/types";
import { Breadcrumbs, Header, BreadcrumbNavigationSearchDropdown } from "@plane/ui";
import { cn } from "@plane/utils";
// The1Studio fork (views-search) — `WorkItemSearchInput` is a controlled, store-free input
// (packages/views-ext/src/search-input.tsx). It is imported from the fork-owned package rather
// than reimplemented here because this surface reuses the exact same search interaction the
// workspace Views tab ships; a package under `packages/` cannot import from `apps/web/core/`
// (plan.md § D6), so the views-ext copy is the shared home.
import { WorkItemSearchInput } from "@plane/views-ext";
// components
import { WorkItemsModal } from "@/components/analytics/work-items/modal";
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { SwitcherLabel } from "@/components/common/switcher-label";
import {
  DisplayFiltersSelection,
  FiltersDropdown,
  LayoutSelection,
  MobileLayoutSelection,
} from "@/components/issues/issue-layouts/filters";
import { ModuleQuickActions } from "@/components/modules";
import { WorkItemFiltersToggle } from "@/components/work-item-filters/filters-toggle";
// hooks
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useIssues } from "@/hooks/store/use-issues";
import { useModule } from "@/hooks/store/use-module";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { useIssuesActions } from "@/hooks/use-issues-actions";
import useLocalStorage from "@/hooks/use-local-storage";
import { usePlatformOS } from "@/hooks/use-platform-os";
// The1Studio fork (views-search) — selector hook for the fork's in-memory `viewsSearchStore`. It
// lives under `core/hooks/store/` (not in `@plane/views-ext`) because a package under `packages/`
// cannot read `StoreContext` — same dependency-direction constraint as D6 in plan.md.
import { useViewsSearch } from "@/hooks/store/use-views-search";
// plane web imports
import { CommonProjectBreadcrumbs } from "@/plane-web/components/breadcrumbs/common";
import { IconButton } from "@plane/propel/icon-button";

export const ModuleIssuesHeader = observer(function ModuleIssuesHeader() {
  // refs
  const parentRef = useRef<HTMLDivElement>(null);
  // states
  const [analyticsModal, setAnalyticsModal] = useState(false);
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId, moduleId: routerModuleId } = useParams();
  const moduleId = routerModuleId ? routerModuleId.toString() : undefined;
  // hooks
  const { isMobile } = usePlatformOS();
  // store hooks
  const {
    issuesFilter: { issueFilters },
    issues,
  } = useIssues(EIssuesStoreType.MODULE);
  const { updateFilters } = useIssuesActions(EIssuesStoreType.MODULE);
  const { projectModuleIds, getModuleById } = useModule();
  const { toggleCreateIssueModal } = useCommandPalette();
  const { allowPermissions } = useUserPermissions();
  const { currentProjectDetails, loader } = useProject();
  // local storage
  const { setValue, storedValue } = useLocalStorage("module_sidebar_collapsed", "false");
  // The1Studio fork (views-search) — ephemeral, per-module search term (plan.md D3). Read-only
  // param assembly happens in filter.store.ts `getAppliedFilters`; this header only writes the
  // term and triggers the re-fetch, it never routes through `updateFilters` (B2) — a term routed
  // through `updateFilters` would PATCH the persisted module filters and change the list for
  // every member.
  const searchStore = useViewsSearch();
  // derived values
  const isSidebarCollapsed = storedValue ? storedValue === "true" : false;
  const activeLayout = issueFilters?.displayFilters?.layout;
  const moduleDetails = moduleId ? getModuleById(moduleId) : undefined;
  const canUserCreateIssue = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT
  );
  const workItemsCount = issues.getGroupIssueCount(undefined, undefined, false);

  // The1Studio fork (views-search) — the MODULE store's search key is an opaque composite
  // `${EIssuesStoreType.MODULE}:${moduleId}` so that a module and another entity (cycle /
  // project view) that might share an id can never collide in `viewsSearchStore`.
  const moduleSearchKey = `${EIssuesStoreType.MODULE}:${moduleId}`;

  // The1Studio fork (views-search) — the term for the module currently on screen. The layout
  // mounts the header once for the whole `modules/(detail)` route and the page below swaps per
  // `moduleId` inside the Outlet, so reading the term keyed by `moduleId` (rather than
  // remembering it in a local state) is what makes switching modules show the right term. A
  // missing or empty term is `""` (never `undefined`) per the store contract.
  const searchQuery = moduleId ? searchStore.getSearchQuery(moduleSearchKey) : "";

  // The1Studio fork (views-search) — 300ms debounce (deliberately shorter than the 800ms write
  // debounce in use-workload-estimate-editor.ts: that one guards a server WRITE, this one guards
  // a read). Reuses `issues.fetchIssuesWithExistingPagination`, the same re-fetch path a filter
  // change takes (filter.store.ts:261), which keeps cursor handling, grouped pagination and
  // loader states consistent with a filter change. `issues` comes from the stable mobx store
  // instance via `useIssues`, so the debounced wrapper is safe to create once.
  const debouncedRefetchIssues = useMemo(
    () =>
      debounce((workspaceSlugParam: string, projectIdParam: string, targetModuleId: string) => {
        issues.fetchIssuesWithExistingPagination(workspaceSlugParam, projectIdParam, "mutation", targetModuleId);
      }, 300),
    [issues]
  );

  // The1Studio fork (views-search) — cancel the pending debounce on unmount so a stale term
  // change can never schedule a re-fetch for a module/page that is already gone.
  useEffect(() => () => debouncedRefetchIssues.cancel(), [debouncedRefetchIssues]);

  // The1Studio fork (views-search) — 3B.3 (plan.md): clear the term for the module being left,
  // whether that is a switch to a different module or navigating out of the module page
  // entirely. `ModuleIssuesHeader` mounts once for the whole `modules/(detail)` layout
  // (layout.tsx wraps an <Outlet/> whose child page changes per moduleId; the header itself does
  // not remount on a moduleId change), so this effect's cleanup — not a bare unmount — is what
  // fires on every module switch. Without it, returning to a module visited earlier in the
  // session would resurrect its old term. Also fires the transition-to-empty re-fetch (clearing
  // the box restores the full list) when the term being cleared actually transitioned to empty.
  useEffect(
    () => () => {
      const previousQuery = searchStore.getSearchQuery(moduleSearchKey);
      if (moduleId) {
        if (previousQuery !== "" && workspaceSlug && projectId)
          issues.fetchIssuesWithExistingPagination(
            workspaceSlug.toString(),
            projectId.toString(),
            "mutation",
            moduleId
          );
        searchStore.clearSearchQuery(moduleSearchKey);
      }
    },
    [moduleId, moduleSearchKey, workspaceSlug, projectId, issues, searchStore]
  );

  // The1Studio fork (views-search) — writes the term immediately (controlled input, no input
  // lag) and schedules the debounced re-fetch. Not gated on any permission: search never mutates
  // the module (unlike the layout switcher / display dropdown), so a read-only user still
  // searches.
  const updateSearchQuery = useCallback(
    (query: string) => {
      if (!moduleId) return;
      searchStore.setSearchQuery(moduleSearchKey, query);
      if (!workspaceSlug || !projectId) return;
      debouncedRefetchIssues(workspaceSlug.toString(), projectId.toString(), moduleId);
    },
    [moduleId, moduleSearchKey, workspaceSlug, projectId, searchStore, debouncedRefetchIssues]
  );

  const toggleSidebar = () => {
    setValue(`${!isSidebarCollapsed}`);
  };

  const handleLayoutChange = useCallback(
    (layout: EIssueLayoutTypes) => {
      if (!projectId) return;
      updateFilters(projectId.toString(), EIssueFilterType.DISPLAY_FILTERS, { layout: layout });
    },
    [projectId, updateFilters]
  );

  const handleDisplayFilters = useCallback(
    (updatedDisplayFilter: Partial<IIssueDisplayFilterOptions>) => {
      if (!projectId) return;
      updateFilters(projectId.toString(), EIssueFilterType.DISPLAY_FILTERS, updatedDisplayFilter);
    },
    [projectId, updateFilters]
  );

  const handleDisplayProperties = useCallback(
    (property: Partial<IIssueDisplayProperties>) => {
      if (!projectId) return;
      updateFilters(projectId.toString(), EIssueFilterType.DISPLAY_PROPERTIES, property);
    },
    [projectId, updateFilters]
  );

  const switcherOptions = projectModuleIds
    ?.map((id) => {
      const _module = id === moduleId ? moduleDetails : getModuleById(id);
      if (!_module) return;
      return {
        value: _module.id,
        query: _module.name,
        content: <SwitcherLabel name={_module.name} LabelIcon={ModuleIcon} />,
      };
    })
    .filter((option) => option !== undefined) as ICustomSearchSelectOption[];

  return (
    <>
      <WorkItemsModal
        isOpen={analyticsModal}
        onClose={() => setAnalyticsModal(false)}
        moduleDetails={moduleDetails ?? undefined}
        projectDetails={currentProjectDetails}
      />
      <Header>
        <Header.LeftItem>
          <div className="flex items-center gap-2">
            <Breadcrumbs onBack={router.back} isLoading={loader === "init-loader"}>
              <CommonProjectBreadcrumbs workspaceSlug={workspaceSlug?.toString()} projectId={projectId?.toString()} />
              <Breadcrumbs.Item
                component={
                  <BreadcrumbLink
                    label="Modules"
                    href={`/${workspaceSlug}/projects/${projectId}/modules/`}
                    icon={<ModuleIcon className="h-4 w-4 text-tertiary" />}
                    isLast
                  />
                }
                isLast
              />
              <Breadcrumbs.Item
                component={
                  <BreadcrumbNavigationSearchDropdown
                    selectedItem={moduleId?.toString() ?? ""}
                    navigationItems={switcherOptions}
                    onChange={(value: string) => {
                      router.push(`/${workspaceSlug}/projects/${projectId}/modules/${value}`);
                    }}
                    title={moduleDetails?.name}
                    icon={<ModuleIcon className="size-3.5 flex-shrink-0 text-tertiary" />}
                    isLast
                  />
                }
              />
            </Breadcrumbs>
            {workItemsCount && workItemsCount > 0 ? (
              <Tooltip
                isMobile={isMobile}
                tooltipContent={`There are ${workItemsCount} ${
                  workItemsCount > 1 ? "work items" : "work item"
                } in this module`}
                position="bottom"
              >
                <span className="flex flex-shrink-0 cursor-default items-center justify-center rounded-xl bg-accent-primary/20 px-2 text-center text-11 font-semibold text-accent-primary">
                  {workItemsCount}
                </span>
              </Tooltip>
            ) : null}
          </div>
        </Header.LeftItem>
        <Header.RightItem className="items-center">
          {/* The1Studio fork (views-search) — placed first so reading order is search → layout
              → filters → display → create, matching the workspace Views tab (plan.md 3B.1).
              Gated on moduleId only, never on a permission: search is ephemeral and never
              mutates the module, so a read-only member still searches. */}
          {moduleId && <WorkItemSearchInput searchQuery={searchQuery} updateSearchQuery={updateSearchQuery} />}
          <div className="hidden gap-2 md:flex">
            <div className="hidden @4xl:flex">
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
            </div>
            <div className="flex @4xl:hidden">
              <MobileLayoutSelection
                layouts={[
                  EIssueLayoutTypes.LIST,
                  EIssueLayoutTypes.KANBAN,
                  EIssueLayoutTypes.CALENDAR,
                  EIssueLayoutTypes.SPREADSHEET,
                  EIssueLayoutTypes.GANTT,
                ]}
                onChange={(layout) => handleLayoutChange(layout)}
                activeLayout={activeLayout}
              />
            </div>
            {moduleId && <WorkItemFiltersToggle entityType={EIssuesStoreType.MODULE} entityId={moduleId} />}
            <FiltersDropdown
              title="Display"
              placement="bottom-end"
              miniIcon={<SlidersHorizontal className="size-3.5" />}
            >
              <DisplayFiltersSelection
                layoutDisplayFiltersOptions={
                  activeLayout ? ISSUE_DISPLAY_FILTERS_BY_PAGE.issues.layoutOptions[activeLayout] : undefined
                }
                displayFilters={issueFilters?.displayFilters ?? {}}
                handleDisplayFiltersUpdate={handleDisplayFilters}
                displayProperties={issueFilters?.displayProperties ?? {}}
                handleDisplayPropertiesUpdate={handleDisplayProperties}
                ignoreGroupedFilters={["module"]}
                cycleViewDisabled={!currentProjectDetails?.cycle_view}
                moduleViewDisabled={!currentProjectDetails?.module_view}
              />
            </FiltersDropdown>
          </div>

          {canUserCreateIssue ? (
            <>
              <Button className="hidden md:block" onClick={() => setAnalyticsModal(true)} variant="secondary" size="lg">
                <span className="hidden @4xl:flex">Analytics</span>
                <span className="@4xl:hidden">
                  <ChartNoAxesColumn className="size-3.5" />
                </span>
              </Button>
              <Button
                variant="primary"
                size="lg"
                className="hidden sm:flex"
                onClick={() => {
                  toggleCreateIssueModal(true, EIssuesStoreType.MODULE);
                }}
                data-ph-element={WORK_ITEM_TRACKER_ELEMENTS.HEADER_ADD_BUTTON.MODULE}
              >
                Add work item
              </Button>
            </>
          ) : (
            <></>
          )}
          <IconButton
            variant="tertiary"
            size="lg"
            icon={PanelRight}
            onClick={toggleSidebar}
            className={cn({
              "bg-accent-subtle text-accent-primary": !isSidebarCollapsed,
            })}
          />
          {moduleId && (
            <ModuleQuickActions
              parentRef={parentRef}
              moduleId={moduleId}
              projectId={projectId.toString()}
              workspaceSlug={workspaceSlug.toString()}
              customClassName="flex-shrink-0 flex items-center justify-center bg-layer-1/70 rounded-sm size-[26px]"
            />
          )}
        </Header.RightItem>
      </Header>
    </>
  );
});
