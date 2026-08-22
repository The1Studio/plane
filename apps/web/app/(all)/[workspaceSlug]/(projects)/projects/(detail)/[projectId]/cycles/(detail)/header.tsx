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
  EUserPermissions,
  EUserPermissionsLevel,
  ISSUE_DISPLAY_FILTERS_BY_PAGE,
  WORK_ITEM_TRACKER_ELEMENTS,
} from "@plane/constants";
import { usePlatformOS } from "@plane/hooks";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { IconButton } from "@plane/propel/icon-button";
import { CycleIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import type { ICustomSearchSelectOption, IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
import { EIssuesStoreType, EIssueLayoutTypes } from "@plane/types";
import { Breadcrumbs, BreadcrumbNavigationSearchDropdown, Header } from "@plane/ui";
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
import { CycleQuickActions } from "@/components/cycles/quick-actions";
import {
  DisplayFiltersSelection,
  FiltersDropdown,
  LayoutSelection,
  MobileLayoutSelection,
} from "@/components/issues/issue-layouts/filters";
import { WorkItemFiltersToggle } from "@/components/work-item-filters/filters-toggle";
// hooks
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useCycle } from "@/hooks/store/use-cycle";
import { useIssues } from "@/hooks/store/use-issues";
// The1Studio fork (views-search) — selector hook for the fork's in-memory `viewsSearchStore`.
// It lives under `core/hooks/store/` (not in `@plane/views-ext`) because a package under
// `packages/` cannot read `StoreContext` — same dependency-direction constraint as D6 in plan.md.
import { useViewsSearch } from "@/hooks/store/use-views-search";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import useLocalStorage from "@/hooks/use-local-storage";
// plane web imports
import { CommonProjectBreadcrumbs } from "@/plane-web/components/breadcrumbs/common";

export const CycleIssuesHeader = observer(function CycleIssuesHeader() {
  // refs
  const parentRef = useRef<HTMLDivElement>(null);
  // states
  const [analyticsModal, setAnalyticsModal] = useState(false);
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId, cycleId } = useParams();
  // i18n
  const { t } = useTranslation();
  // store hooks
  const {
    issuesFilter: { issueFilters, updateFilters },
    issues,
  } = useIssues(EIssuesStoreType.CYCLE);
  const { currentProjectCycleIds, getCycleById } = useCycle();
  const { toggleCreateIssueModal } = useCommandPalette();
  const { currentProjectDetails, loader } = useProject();
  const { isMobile } = usePlatformOS();
  const { allowPermissions } = useUserPermissions();
  // The1Studio fork (views-search) — ephemeral, per-cycle search term store (plan.md D3). Read-only
  // param assembly happens in filter.store.ts `getAppliedFilters`; this header only writes the term
  // and triggers the re-fetch, it never routes through `updateFilters` (B2) — a term routed through
  // `updateFilters` would PATCH the persisted cycle filters and change the list for every member.
  const searchStore = useViewsSearch();

  const activeLayout = issueFilters?.displayFilters?.layout;

  const { setValue, storedValue } = useLocalStorage("cycle_sidebar_collapsed", false);

  const isSidebarCollapsed = storedValue === true;
  const toggleSidebar = () => {
    setValue(!isSidebarCollapsed);
  };

  const handleLayoutChange = useCallback(
    (layout: EIssueLayoutTypes) => {
      if (!workspaceSlug || !projectId) return;
      updateFilters(workspaceSlug, projectId, EIssueFilterType.DISPLAY_FILTERS, { layout: layout }, cycleId);
    },
    [workspaceSlug, projectId, cycleId, updateFilters]
  );

  const handleDisplayFilters = useCallback(
    (updatedDisplayFilter: Partial<IIssueDisplayFilterOptions>) => {
      if (!workspaceSlug || !projectId) return;
      updateFilters(workspaceSlug, projectId, EIssueFilterType.DISPLAY_FILTERS, updatedDisplayFilter, cycleId);
    },
    [workspaceSlug, projectId, cycleId, updateFilters]
  );

  const handleDisplayProperties = useCallback(
    (property: Partial<IIssueDisplayProperties>) => {
      if (!workspaceSlug || !projectId) return;
      updateFilters(workspaceSlug, projectId, EIssueFilterType.DISPLAY_PROPERTIES, property, cycleId);
    },
    [workspaceSlug, projectId, cycleId, updateFilters]
  );

  // derived values
  const cycleDetails = cycleId ? getCycleById(cycleId.toString()) : undefined;
  const isCompletedCycle = cycleDetails?.status?.toLocaleLowerCase() === "completed";
  const canUserCreateIssue = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT
  );

  const switcherOptions = currentProjectCycleIds
    ?.map((id) => {
      const _cycle = id === cycleId ? cycleDetails : getCycleById(id);
      if (!_cycle) return;
      return {
        value: _cycle.id,
        query: _cycle.name,
        content: <SwitcherLabel name={_cycle.name} LabelIcon={CycleIcon} />,
      };
    })
    .filter((option) => option !== undefined) as ICustomSearchSelectOption[];

  const workItemsCount = issues.getGroupIssueCount(undefined, undefined, false);

  // The1Studio fork (views-search) — the CYCLE store's search key is an opaque composite
  // `${EIssuesStoreType.CYCLE}:${cycleId}` so that a cycle and another entity (module / project
  // view) that might share an id can never collide in `viewsSearchStore`.
  const cycleSearchKey = `${EIssuesStoreType.CYCLE}:${cycleId}`;

  // The1Studio fork (views-search) — the term for the cycle currently on screen. The layout
  // mounts the header once for the whole `cycles/(detail)` route and the page below swaps per
  // `cycleId` inside the Outlet, so reading the term keyed by `cycleId` (rather than remembering
  // it in a local state) is what makes switching cycles show the right term. A missing or empty
  // term is `""` (never `undefined`) per the store contract.
  const searchQuery = searchStore.getSearchQuery(cycleSearchKey);

  // The1Studio fork (views-search) — 300ms debounce (deliberately shorter than the 800ms write
  // debounce in use-workload-estimate-editor.ts: that one guards a server WRITE, this one guards
  // a read). Reuses `cycleIssues.fetchIssuesWithExistingPagination`, the same re-fetch path a
  // filter change takes (filter.store.ts:256), which keeps cursor handling, grouped pagination
  // and loader states consistent with a filter change. `issues`/`cycleIssues` comes from the
  // stable mobx store instance via `useIssues`, so the debounced wrapper is safe to create once.
  const debouncedRefetchIssues = useMemo(
    () =>
      debounce((workspaceSlugParam: string, projectIdParam: string, targetCycleId: string) => {
        issues.fetchIssuesWithExistingPagination(workspaceSlugParam, projectIdParam, "mutation", targetCycleId);
      }, 300),
    [issues]
  );

  // The1Studio fork (views-search) — cancel the pending debounce on unmount so a stale term
  // change can never schedule a re-fetch for a cycle/page that is already gone.
  useEffect(() => () => debouncedRefetchIssues.cancel(), [debouncedRefetchIssues]);

  // The1Studio fork (views-search) — 3B.3 (plan.md): clear the term for the cycle being left,
  // whether that is a switch to a different cycle or navigating out of the cycle page entirely.
  // `CycleIssuesHeader` mounts once for the whole `cycles/(detail)` layout (layout.tsx wraps an
  // <Outlet/> whose child page changes per cycleId; the header itself does not remount on a
  // cycleId change), so this effect's cleanup — not a bare unmount — is what fires on every
  // cycle switch. Without it, returning to a cycle visited earlier in the session would
  // resurrect its old term. Also fires the transition-to-empty re-fetch (clearing the box
  // restores the full list) when the term being cleared actually transitioned to empty.
  useEffect(
    () => () => {
      const previousQuery = searchStore.getSearchQuery(cycleSearchKey);
      if (cycleId) {
        if (previousQuery !== "" && workspaceSlug && projectId)
          issues.fetchIssuesWithExistingPagination(
            workspaceSlug.toString(),
            projectId.toString(),
            "mutation",
            cycleId.toString()
          );
        searchStore.clearSearchQuery(cycleSearchKey);
      }
    },
    [cycleId, cycleSearchKey, workspaceSlug, projectId, issues, searchStore]
  );

  // The1Studio fork (views-search) — writes the term immediately (controlled input, no input lag)
  // and schedules the debounced re-fetch. Not gated on any permission: search never mutates the
  // cycle (unlike the layout switcher / display dropdown), so a read-only user still searches.
  const updateSearchQuery = useCallback(
    (query: string) => {
      if (!cycleId) return;
      searchStore.setSearchQuery(cycleSearchKey, query);
      if (!workspaceSlug || !projectId) return;
      debouncedRefetchIssues(workspaceSlug.toString(), projectId.toString(), cycleId.toString());
    },
    [cycleId, cycleSearchKey, workspaceSlug, projectId, searchStore, debouncedRefetchIssues]
  );

  return (
    <>
      <WorkItemsModal
        projectDetails={currentProjectDetails}
        isOpen={analyticsModal}
        onClose={() => setAnalyticsModal(false)}
        cycleDetails={cycleDetails ?? undefined}
      />
      <Header>
        <Header.LeftItem>
          <div className="flex items-center gap-2">
            <Breadcrumbs onBack={router.back} isLoading={loader === "init-loader"}>
              <CommonProjectBreadcrumbs workspaceSlug={workspaceSlug?.toString()} projectId={projectId?.toString()} />
              <Breadcrumbs.Item
                component={
                  <BreadcrumbLink
                    label="Cycles"
                    href={`/${workspaceSlug}/projects/${projectId}/cycles/`}
                    icon={<CycleIcon className="h-4 w-4 text-tertiary" />}
                  />
                }
              />
              <Breadcrumbs.Item
                component={
                  <BreadcrumbNavigationSearchDropdown
                    selectedItem={cycleId}
                    navigationItems={switcherOptions}
                    onChange={(value: string) => {
                      router.push(`/${workspaceSlug}/projects/${projectId}/cycles/${value}`);
                    }}
                    title={cycleDetails?.name}
                    icon={
                      <Breadcrumbs.Icon>
                        <CycleIcon className="size-4 flex-shrink-0 text-tertiary" />
                      </Breadcrumbs.Icon>
                    }
                    isLast
                  />
                }
                isLast
              />
            </Breadcrumbs>
            {workItemsCount && workItemsCount > 0 ? (
              <Tooltip
                isMobile={isMobile}
                tooltipContent={`There are ${workItemsCount} ${
                  workItemsCount > 1 ? "work items" : "work item"
                } in this cycle`}
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
              Gated on cycleId only, never on a permission: search is ephemeral and never
              mutates the cycle, so a read-only member still searches. */}
          {cycleId && <WorkItemSearchInput searchQuery={searchQuery} updateSearchQuery={updateSearchQuery} />}
          <div className="hidden items-center gap-2 md:flex">
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
            <WorkItemFiltersToggle entityType={EIssuesStoreType.CYCLE} entityId={cycleId} />
            <FiltersDropdown
              title={t("common.display")}
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
                ignoreGroupedFilters={["cycle"]}
                cycleViewDisabled={!currentProjectDetails?.cycle_view}
                moduleViewDisabled={!currentProjectDetails?.module_view}
              />
            </FiltersDropdown>

            {canUserCreateIssue && (
              <>
                <Button onClick={() => setAnalyticsModal(true)} variant="secondary" size="lg">
                  <span className="hidden @4xl:flex">Analytics</span>
                  <span className="@4xl:hidden">
                    <ChartNoAxesColumn className="size-3.5" />
                  </span>
                </Button>
                {!isCompletedCycle && (
                  <Button
                    variant="primary"
                    size="lg"
                    onClick={() => {
                      toggleCreateIssueModal(true, EIssuesStoreType.CYCLE);
                    }}
                    data-ph-element={WORK_ITEM_TRACKER_ELEMENTS.HEADER_ADD_BUTTON.CYCLE}
                  >
                    {t("issue.add.label")}
                  </Button>
                )}
              </>
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
            <CycleQuickActions
              parentRef={parentRef}
              cycleId={cycleId}
              projectId={projectId}
              workspaceSlug={workspaceSlug}
              customClassName="flex-shrink-0 flex items-center justify-center size-[26px] bg-layer-1/70 rounded-sm"
            />
          </div>
        </Header.RightItem>
      </Header>
    </>
  );
});
