// The1Studio fork (views-layouts)
//
// Layout-aware query-param builder for the workspace Views tab (the GLOBAL issue store).
//
// Resolves B1 (plan.md): `apps/web/core/store/issue/workspace/filter.store.ts` hardcodes
// `handleIssueQueryParamsByLayout(EIssueLayoutTypes.SPREADSHEET, "my_issues")` regardless of
// the active layout. Every sibling store (cycle, module, archived, profile) passes
// `userFilters?.displayFilters?.layout` instead — until this is layout-aware, switching
// layout re-renders the component but never changes the request, so `group_by` never reaches
// the server and Board always renders one column. Phase 3 replaces that hardcoded call with
// this function, passing the active layout.
//
// Mirrors `handleIssueQueryParamsByLayout` (@plane/utils, packages/utils/src/work-item/base.ts)
// exactly — same derivation from `display_filters` keys plus `extra_options` — so behaviour
// stays consistent with the rest of the app. Do NOT "improve" this derivation; the one
// intentional difference is the source table: `GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS` (this
// package) instead of `ISSUE_DISPLAY_FILTERS_BY_PAGE[viewType].layoutOptions`, because the
// closest upstream viewType (`my_issues`) has no entries for `kanban`/`calendar`/`gantt_chart`
// (B2, plan.md).

import type { TIssueParams } from "@plane/types";
import type { EIssueLayoutTypes } from "@plane/types";
import { GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS } from "./layout-options";

/**
 * Returns the `TIssueParams[]` to send for the given layout on the workspace Views tab, or
 * `null` when no layout is active yet (mirrors the upstream function's contract exactly).
 *
 * Throws — rather than silently falling back to a flat/unfiltered param list — when `layout`
 * has no entry in `GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS`. Every layout `GLOBAL_VIEW_LAYOUTS` can
 * ever select IS covered, so this only fires if a layout is added to the switcher without a
 * matching table entry (`rules/development-principles.md` § Errors Over Silent Fallbacks).
 */
export const getGlobalViewQueryParamsByLayout = (layout: EIssueLayoutTypes | undefined): TIssueParams[] | null => {
  if (!layout) return null;

  const currentViewLayoutOptions = GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS[layout];
  if (!currentViewLayoutOptions) {
    throw new Error(
      `getGlobalViewQueryParamsByLayout: no layout options registered for layout "${layout}" in GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS (packages/views-ext)`
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
};
