// The1Studio fork (views-search)
//
// Resolves B1 (plan.md): `search` is not a member of upstream's sealed `TIssueParams`
// (packages/types/src/view-props.ts), and `docs/FORK.md` seals `@plane/types` — the param the
// fork's views-ext endpoint accepts cannot be named from the sealed type. This file widens it
// from the fork side instead.
//
// `TViewsExtIssueParams` is written as a UNION with the sealed type (not an interface with a
// redeclared member) so that if upstream ever adds `search` to `TIssueParams`, this collapses
// to `TIssueParams` harmlessly instead of producing a conflicting declaration.
//
// Pinned contract (shared with the server half, Phase 1):
//   query parameter name: search · type: string · empty or absent -> no filtering applied.

import type { TIssueParams } from "@plane/types";

/** The1Studio fork (views-search) — `TIssueParams` widened by the params the fork sends.
 *
 * TWO params, because the two endpoint families accept different things — see
 * `withGlobalViewSearch` vs `withEntityNameSearch` below. Neither is a member of the sealed
 * upstream type, so both are widened here.
 */
export type TViewsExtIssueParams = TIssueParams | "search" | "name";

/**
 * Returns `params` plus the fork's `search` param for the workspace Views tab request.
 *
 * - A blank or whitespace-only `searchQuery` returns `params` UNCHANGED — the `search` key is
 *   absent, not present-and-empty. This is the client half of the contract's "empty ≡ absent"
 *   rule; omitting the param keeps request URLs and request de-duplication clean.
 * - Otherwise returns a NEW object with `search` set to the trimmed term. The input is never
 *   mutated — core `getAppliedFilters` callers assume a fresh object.
 * - Pure and free of store imports: Phase 3 supplies the term.
 */
// The value union is `string | boolean` — NOT widened with `string[]`. It must match
// `IssueFilterHelperStore.getPaginationParams`, which takes
// `Partial<Record<TIssueParams, string | boolean>>`
// (apps/web/core/store/issue/helpers/issue-filter-helper.store.ts:300). A `string[]` member here
// makes this function's return non-assignable to that parameter, and the wiring in
// `getAppliedFilters` fails to typecheck. Widen the KEY (that is this file's job), never the value.
export function withGlobalViewSearch(
  params: Partial<Record<TIssueParams, string | boolean>>,
  searchQuery: string
): Partial<Record<TViewsExtIssueParams, string | boolean>> {
  const trimmed = searchQuery.trim();
  if (trimmed === "") return params;
  return { ...params, search: trimmed };
}

/**
 * The1Studio fork (views-search) — the same idea as `withGlobalViewSearch` above, but emitting
 * `name` instead of `search`, for the four PROJECT-SCOPED work-item lists (Project Work Items,
 * Module, Cycle, Project Views).
 *
 * WHY TWO FUNCTIONS RATHER THAN ONE PARAMETERISED BY KEY: the two endpoint families genuinely
 * accept different parameters, and getting them backwards fails SILENTLY rather than loudly.
 *
 *   - The workspace Views tab hits the fork's own endpoint
 *     (`/api/views-ext/workspaces/<slug>/issues/`), which accepts `search` and matches name +
 *     whole-integer sequence_id + project identifier via `plane.utils.issue_search.search_issues`.
 *   - These four hit CORE's `/api/workspaces/<slug>/projects/<id>/issues/`, which accepts `name`
 *     (dispatched to `name__icontains` by `plane/utils/issue_filters.py` `filter_name`) and
 *     **ignores `search` entirely — no error, just an unfiltered result set**. Sending the wrong
 *     key here would look like a working search box returning everything.
 *
 * CONSEQUENCE, deliberately accepted: on these four surfaces a full identifier such as
 * "PLANE-79" matches NOTHING, because `name__icontains` only searches the title. The same string
 * resolves on the Views tab. Closing that gap needs `search_issues()` called on core's
 * `IssueViewSet.list` — a core-file edit, i.e. a documented `docs/FORK.md` exception — which was
 * considered and not taken.
 *
 * Same contract as its sibling otherwise: a blank or whitespace-only term returns `params`
 * unchanged with NO `name` key (core's `filter_name` also no-ops on an empty value, so this is
 * belt-and-braces), the input is never mutated, and the value union stays `string | boolean` to
 * remain assignable to `getPaginationParams`.
 */
export function withEntityNameSearch(
  params: Partial<Record<TIssueParams, string | boolean>>,
  searchQuery: string
): Partial<Record<TViewsExtIssueParams, string | boolean>> {
  const trimmed = searchQuery.trim();
  if (trimmed === "") return params;
  return { ...params, name: trimmed };
}
