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

/** The1Studio fork (views-search) — `TIssueParams` widened by the one param the fork adds. */
export type TViewsExtIssueParams = TIssueParams | "search";

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
