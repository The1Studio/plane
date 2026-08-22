/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { debounce } from "lodash-es";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import {
  EIssueFilterType,
  ISSUE_DISPLAY_FILTERS_BY_PAGE,
  GLOBAL_VIEW_TRACKER_ELEMENTS,
  DEFAULT_GLOBAL_VIEWS_LIST,
} from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { ViewsIcon } from "@plane/propel/icons";
import type { IIssueDisplayFilterOptions, IIssueDisplayProperties, ICustomSearchSelectOption } from "@plane/types";
import { EIssuesStoreType, EIssueLayoutTypes } from "@plane/types";
import { Breadcrumbs, Header, BreadcrumbNavigationSearchDropdown } from "@plane/ui";
// The1Studio fork (views-search)
import { WorkItemSearchInput } from "@plane/views-ext";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { SwitcherLabel } from "@/components/common/switcher-label";
import { DisplayFiltersSelection, FiltersDropdown } from "@/components/issues/issue-layouts/filters";
import { WorkItemFiltersToggle } from "@/components/work-item-filters/filters-toggle";
import { DefaultWorkspaceViewQuickActions } from "@/components/workspace/views/default-view-quick-action";
import { CreateUpdateWorkspaceViewModal } from "@/components/workspace/views/modal";
import { WorkspaceViewQuickActions } from "@/components/workspace/views/quick-action";
// hooks
import { useGlobalView } from "@/hooks/store/use-global-view";
import { useIssues } from "@/hooks/store/use-issues";
// The1Studio fork (views-search)
import { useViewsSearch } from "@/hooks/store/use-views-search";
import { useAppRouter } from "@/hooks/use-app-router";
import { GlobalViewLayoutSelection } from "@/plane-web/components/views/helper";

export const GlobalIssuesHeader = observer(function GlobalIssuesHeader() {
  // states
  const [createViewModal, setCreateViewModal] = useState(false);
  // router
  const router = useAppRouter();
  const { workspaceSlug, globalViewId: routerGlobalViewId } = useParams();
  const globalViewId = routerGlobalViewId ? routerGlobalViewId.toString() : undefined;
  // store hooks
  const {
    issuesFilter: { filters, updateFilters },
    issues,
  } = useIssues(EIssuesStoreType.GLOBAL);
  const { getViewDetailsById, currentWorkspaceViews } = useGlobalView();
  const { t } = useTranslation();
  // The1Studio fork (views-search) — ephemeral, per-view search term (plan.md D3). Read-only
  // param assembly happens in filter.store.ts `getAppliedFilters`; this header only writes the
  // term and triggers the re-fetch, it never routes through `updateFilters` (B2).
  const searchStore = useViewsSearch();

  const issueFilters = globalViewId ? filters[globalViewId.toString()] : undefined;

  const activeLayout = issueFilters?.displayFilters?.layout;
  const viewDetails = globalViewId ? getViewDetailsById(globalViewId) : undefined;

  const handleDisplayFilters = useCallback(
    (updatedDisplayFilter: Partial<IIssueDisplayFilterOptions>) => {
      if (!workspaceSlug || !globalViewId) return;
      updateFilters(
        workspaceSlug.toString(),
        undefined,
        EIssueFilterType.DISPLAY_FILTERS,
        updatedDisplayFilter,
        globalViewId
      );
    },
    [workspaceSlug, updateFilters, globalViewId]
  );

  const handleDisplayProperties = useCallback(
    (property: Partial<IIssueDisplayProperties>) => {
      if (!workspaceSlug || !globalViewId) return;
      updateFilters(workspaceSlug.toString(), undefined, EIssueFilterType.DISPLAY_PROPERTIES, property, globalViewId);
    },
    [workspaceSlug, updateFilters, globalViewId]
  );

  const handleLayoutChange = useCallback(
    (layout: EIssueLayoutTypes) => {
      if (!workspaceSlug || !globalViewId) return;
      updateFilters(
        workspaceSlug.toString(),
        undefined,
        EIssueFilterType.DISPLAY_FILTERS,
        { layout: layout },
        globalViewId
      );
    },
    [workspaceSlug, updateFilters, globalViewId]
  );

  const isLocked = viewDetails?.is_locked;

  const isDefaultView = DEFAULT_GLOBAL_VIEWS_LIST.find((view) => view.key === globalViewId);

  const defaultViewDetails = DEFAULT_GLOBAL_VIEWS_LIST.find((view) => view.key === globalViewId);

  const defaultOptions = DEFAULT_GLOBAL_VIEWS_LIST.map((view) => ({
    value: view.key,
    query: view.key,
    content: <SwitcherLabel name={t(view.i18n_label)} LabelIcon={ViewsIcon} />,
  }));

  const workspaceOptions = (currentWorkspaceViews || []).map((view) => {
    const _view = getViewDetailsById(view);
    if (!_view) return;
    return {
      value: _view.id,
      query: _view.name,
      content: <SwitcherLabel name={_view.name} LabelIcon={ViewsIcon} />,
    };
  });

  const switcherOptions = [...defaultOptions, ...workspaceOptions].filter(
    (option) => option !== undefined
  ) as ICustomSearchSelectOption[];
  const currentLayoutFilters = useMemo(() => {
    const layout = activeLayout ?? EIssueLayoutTypes.SPREADSHEET;
    return ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions[layout];
  }, [activeLayout]);

  // The1Studio fork (views-search) — the search term for the view currently on screen. The
  // store is keyed by viewId (plan.md D3), so switching views never shows a stale term.
  const searchQuery = globalViewId ? searchStore.getSearchQuery(globalViewId) : "";

  // The1Studio fork (views-search) — 300ms debounce (deliberately shorter than the 800ms
  // write-debounce in use-workload-estimate-editor.ts: that one guards a server WRITE, this one
  // guards a read). Reuses `fetchIssuesWithExistingPagination`, the same re-fetch path a filter
  // change takes (filter.store.ts:233/287), which keeps cursor handling, grouped pagination and
  // loader states consistent with a filter change. `issues` is a stable mobx store instance for
  // the lifetime of this component, so the debounced wrapper is safe to create once.
  const debouncedRefetchIssues = useMemo(
    () =>
      debounce((workspaceSlugParam: string, viewId: string) => {
        issues.fetchIssuesWithExistingPagination(workspaceSlugParam, viewId, "mutation");
      }, 300),
    [issues]
  );

  useEffect(() => () => debouncedRefetchIssues.cancel(), [debouncedRefetchIssues]);

  // The1Studio fork (views-search) — 3B.3 (plan.md): clear the term for the view being left,
  // whether that's a switch to a different view or navigating out of the Views tab entirely.
  // `GlobalIssuesHeader` mounts once for the whole `workspace-views/*` layout (layout.tsx wraps
  // an <Outlet/> whose child page changes per viewId; the header itself does not remount on a
  // viewId change), so this effect's cleanup — not a bare unmount — is what fires on every view
  // switch. Without it, returning to a view visited earlier in the session would resurrect its
  // old term.
  useEffect(
    () => () => {
      if (globalViewId) searchStore.clearSearchQuery(globalViewId);
    },
    [globalViewId, searchStore]
  );

  // The1Studio fork (views-search) — writes the term immediately (controlled input, no input
  // lag) and schedules the debounced re-fetch. Not gated on `!isLocked`: search never mutates
  // the view (unlike the layout switcher / display dropdown below, which are hidden when
  // locked), so a locked view still searches.
  const updateSearchQuery = useCallback(
    (query: string) => {
      if (!globalViewId) return;
      searchStore.setSearchQuery(globalViewId, query);
      if (!workspaceSlug) return;
      debouncedRefetchIssues(workspaceSlug.toString(), globalViewId);
    },
    [globalViewId, workspaceSlug, searchStore, debouncedRefetchIssues]
  );

  return (
    <>
      <CreateUpdateWorkspaceViewModal isOpen={createViewModal} onClose={() => setCreateViewModal(false)} />
      <Header>
        <Header.LeftItem>
          <Breadcrumbs>
            <Breadcrumbs.Item
              component={<BreadcrumbLink label={t("views")} icon={<ViewsIcon className="h-4 w-4 text-tertiary" />} />}
            />
            <Breadcrumbs.Item
              component={
                <BreadcrumbNavigationSearchDropdown
                  selectedItem={globalViewId?.toString() || ""}
                  navigationItems={switcherOptions}
                  onChange={(value: string) => {
                    router.push(`/${workspaceSlug}/workspace-views/${value}`);
                  }}
                  title={viewDetails?.name ?? t(defaultViewDetails?.i18n_label ?? "")}
                  icon={
                    <Breadcrumbs.Icon>
                      <ViewsIcon className="size-4 flex-shrink-0 text-tertiary" />
                    </Breadcrumbs.Icon>
                  }
                  isLast
                />
              }
              isLast
            />
          </Breadcrumbs>
        </Header.LeftItem>

        <Header.RightItem className="items-center">
          {/* The1Studio fork (views-search) — placed first so reading order is search → layout
              → filters → display → create (plan.md 3B.1). Gated on globalViewId only, not
              !isLocked: search is ephemeral and never mutates the view. */}
          {globalViewId && <WorkItemSearchInput searchQuery={searchQuery} updateSearchQuery={updateSearchQuery} />}
          {!isLocked && (
            <GlobalViewLayoutSelection
              onChange={handleLayoutChange}
              selectedLayout={activeLayout ?? EIssueLayoutTypes.SPREADSHEET}
              workspaceSlug={workspaceSlug.toString()}
            />
          )}
          {globalViewId && <WorkItemFiltersToggle entityType={EIssuesStoreType.GLOBAL} entityId={globalViewId} />}
          {!isLocked && (
            <FiltersDropdown title={t("common.display")} placement="bottom-end">
              <DisplayFiltersSelection
                layoutDisplayFiltersOptions={currentLayoutFilters}
                displayFilters={issueFilters?.displayFilters ?? {}}
                handleDisplayFiltersUpdate={handleDisplayFilters}
                displayProperties={issueFilters?.displayProperties ?? {}}
                handleDisplayPropertiesUpdate={handleDisplayProperties}
              />
            </FiltersDropdown>
          )}
          <Button
            variant="primary"
            size="lg"
            data-ph-element={GLOBAL_VIEW_TRACKER_ELEMENTS.RIGHT_HEADER_ADD_BUTTON}
            onClick={() => setCreateViewModal(true)}
          >
            {t("workspace_views.add_view")}
          </Button>
          <div className="hidden md:block">
            {viewDetails && <WorkspaceViewQuickActions workspaceSlug={workspaceSlug?.toString()} view={viewDetails} />}
            {isDefaultView && defaultViewDetails && (
              <DefaultWorkspaceViewQuickActions workspaceSlug={workspaceSlug?.toString()} view={defaultViewDetails} />
            )}
          </div>
        </Header.RightItem>
      </Header>
    </>
  );
});
