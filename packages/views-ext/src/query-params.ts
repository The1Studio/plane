// The1Studio fork (views-layouts, profile-layouts)
//
// Layout-aware query-param builders for two workspace-level, cross-project issue stores: the
// workspace Views tab (GLOBAL store) and the "Your work" profile pages (PROFILE store).
//
// Resolves B1 (plan.md): `apps/web/core/store/issue/workspace/filter.store.ts` hardcoded
// `handleIssueQueryParamsByLayout(EIssueLayoutTypes.SPREADSHEET, "my_issues")` regardless of
// the active layout. Every sibling store (cycle, module, archived, profile) passes
// `userFilters?.displayFilters?.layout` instead — until GLOBAL was made layout-aware, switching
// layout re-rendered the component but never changed the request, so `group_by` never reached
// the server and Board always rendered one column.
//
// PROFILE's own store (`apps/web/core/store/issue/profile/filter.store.ts`) already passed the
// active layout into `handleIssueQueryParamsByLayout(layout, "profile_issues")` — it was
// layout-aware from the start. What it's missing is layout *coverage*: upstream's
// `profile_issues` table only has `list`/`kanban` entries (see layout-options.ts), so selecting
// Spreadsheet/Calendar/Gantt on a profile page would hit a missing key. `getProfileViewQueryParamsByLayout`
// is the drop-in replacement, sourced from `PROFILE_VIEW_ISSUE_LAYOUT_OPTIONS` instead.
//
// Both builders mirror `handleIssueQueryParamsByLayout` (@plane/utils,
// packages/utils/src/work-item/base.ts) exactly — same derivation from `display_filters` keys
// plus `extra_options` — so behaviour stays consistent with the rest of the app. Do NOT
// "improve" this derivation; the one intentional difference is the source table: this
// package's own tables instead of `ISSUE_DISPLAY_FILTERS_BY_PAGE[viewType].layoutOptions`,
// because the closest upstream viewTypes (`my_issues`, `profile_issues`) don't cover every
// layout either store's switcher can select (B2, plan.md; profile-layouts follow-up).

import type { TFiltersLayoutOptions } from "@plane/constants";
import type { EIssueLayoutTypes, TIssueParams } from "@plane/types";
import { GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS, PROFILE_VIEW_ISSUE_LAYOUT_OPTIONS } from "./layout-options";

/**
 * Shared derivation behind `getGlobalViewQueryParamsByLayout` and
 * `getProfileViewQueryParamsByLayout` below — both stores derive query params from a
 * `TFiltersLayoutOptions` table the exact same way; only the source table and the
 * caller-facing error message differ.
 *
 * Returns `null` when no layout is active yet (mirrors the upstream function's contract
 * exactly).
 *
 * Throws — rather than silently falling back to a flat/unfiltered param list — when `layout`
 * has no entry in the given table. Every layout either store's `*_VIEW_LAYOUTS` array can ever
 * select IS covered, so this only fires if a layout is added to a switcher without a matching
 * table entry (`rules/development-principles.md` § Errors Over Silent Fallbacks).
 */
function queryParamsFromLayoutOptions(
  layoutOptionsTable: TFiltersLayoutOptions,
  layout: EIssueLayoutTypes | undefined,
  callerName: string,
  tableName: string
): TIssueParams[] | null {
  if (!layout) return null;

  const currentViewLayoutOptions = layoutOptionsTable[layout];
  if (!currentViewLayoutOptions) {
    throw new Error(
      `${callerName}: no layout options registered for layout "${layout}" in ${tableName} (packages/views-ext)`
    );
  }

  const queryParams: TIssueParams[] = ["filters"];

  Object.keys(currentViewLayoutOptions.display_filters).forEach((option) => {
    queryParams.push(option as TIssueParams);
  });

  if (currentViewLayoutOptions.extra_options.access) {
    currentViewLayoutOptions.extra_options.values.forEach((option) => {
      queryParams.push(option);
    });
  }

  return queryParams;
}

/**
 * Returns the `TIssueParams[]` to send for the given layout on the workspace Views tab.
 * See `queryParamsFromLayoutOptions` above for the shared contract.
 */
export const getGlobalViewQueryParamsByLayout = (layout: EIssueLayoutTypes | undefined): TIssueParams[] | null =>
  queryParamsFromLayoutOptions(
    GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS,
    layout,
    "getGlobalViewQueryParamsByLayout",
    "GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS"
  );

/**
 * Returns the `TIssueParams[]` to send for the given layout on the "Your work" profile pages
 * (assigned / created / subscribed). See `queryParamsFromLayoutOptions` above for the shared
 * contract.
 */
export const getProfileViewQueryParamsByLayout = (layout: EIssueLayoutTypes | undefined): TIssueParams[] | null =>
  queryParamsFromLayoutOptions(
    PROFILE_VIEW_ISSUE_LAYOUT_OPTIONS,
    layout,
    "getProfileViewQueryParamsByLayout",
    "PROFILE_VIEW_ISSUE_LAYOUT_OPTIONS"
  );
