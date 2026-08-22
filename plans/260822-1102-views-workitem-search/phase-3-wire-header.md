# Phase 3 — Wire the search into the store chain and the Views header

**Parent plan:** [`plan.md`](plan.md) · **Depends on:** Phase 1 **and** Phase 2 (both merged)

## Goal

Typing in the Views-tab header search box narrows the work items rendered by whichever layout is
active, and clears on navigation. Three fenced core-side edits and one new hook; all fork logic
already lives in `packages/views-ext/`.

## File ownership

- `apps/web/ce/store/root.store.ts`
- `apps/web/core/store/issue/workspace/filter.store.ts`
- `apps/web/core/hooks/store/use-views-search.ts` (new)
- `apps/web/app/(all)/[workspaceSlug]/(projects)/workspace-views/header.tsx`

Every edit to an existing file is fenced `The1Studio fork (views-search)`.

## Leaf 3A — Store registration and param delegation (~2h)

### 3A.1 — Register the search store (`apps/web/ce/store/root.store.ts`)

This is the established `ce/` seam for a fork store — `workloadStore` is registered here at lines
9, 21 and 42. Mirror it exactly:

- import `ViewsSearchStore` and `IViewsSearchStore` from `@plane/views-ext`
- declare `viewsSearchStore: IViewsSearchStore;` on the class
- instantiate `this.viewsSearchStore = new ViewsSearchStore();` in the constructor

### 3A.2 — Selector hook (`apps/web/core/hooks/store/use-views-search.ts`, new)

Copy the shape of `apps/web/core/hooks/store/use-workload.ts` verbatim — `useContext(StoreContext)`,
throw if undefined, return `context.viewsSearchStore`. A package hook cannot read `StoreContext`
(same dependency-direction constraint as D6), which is why this selector lives in `core/hooks/store/`
rather than in the package. `use-workload.ts` is the precedent and carries the same rationale.

### 3A.3 — Inject the term at param assembly (`filter.store.ts`)

`getAppliedFilters(viewId)` (lines 107-139) is already a documented fork exception point — line 119
delegates to `getGlobalViewQueryParamsByLayout`. Add a second delegation of the same shape:

- import `withGlobalViewSearch` from `@plane/views-ext` alongside the existing import on line 26
- the store already has a root-store reference (`this.rootIssueStore`, used on line 277); reach the
  search store from there, or accept it via the existing root wiring — **do not** add a new
  constructor parameter, which would change a core signature
- wrap the return value: `return withGlobalViewSearch(filteredRouteParams, searchQuery);`

**Why here and not in `updateFilters`:** blocker B2. `updateFilters` (lines 230-277) persists to
local storage and PATCHes saved views. A term routed through it would be written into a **shared**
workspace view and change what every other member sees. `getAppliedFilters` is read-only param
assembly — the term is applied to the request and to nothing else.

Because `getFilterParams` (line 141) wraps `getAppliedFilters` and is the single input to both
`fetchIssues` (`issue.store.ts:117`) and `fetchNextIssues` (`issue.store.ts:138`), one edit here
makes search apply to first-page loads, "load more", and every layout at once. Do not add the term
at the service layer — that would miss the count queries.

## Leaf 3B — Header mount and re-fetch (~2h)

### 3B.1 — Mount the input (`workspace-views/header.tsx`)

Render `WorkItemSearchInput` from `@plane/views-ext` inside `Header.RightItem` (line 152), placed
**before** `GlobalViewLayoutSelection` (line 155) so reading order is search → layout → filters →
display → create.

Gate on `globalViewId` being present, matching how `WorkItemFiltersToggle` is gated on line 161. Do
**not** gate on `!isLocked`: a locked view forbids changing what the view _is_, and an ephemeral
search never changes the view — the layout switcher and display dropdown are hidden when locked
precisely because they mutate stored state, and search does not.

### 3B.2 — Debounced re-fetch

Wire `updateSearchQuery` so that it:

1. Writes to the search store immediately, so the input stays responsive (controlled input; no lag).
2. After a **300 ms** debounce on the settled value, calls
   `fetchIssuesWithExistingPagination(workspaceSlug, viewId, "mutation")` — the exact call
   `updateFilters` makes on line 277. Reusing that path is what keeps cursor handling, grouped
   pagination and loader states consistent with a filter change; do not hand-roll a fetch.
3. Fires the refetch on a _transition to empty_ as well, so clearing the box restores the full list.

The 300 ms figure is the standard search debounce; it is deliberately shorter than the 800 ms used
by the workload estimate input (`use-workload-estimate-editor.ts`), because that debounce guards a
_write_ to the server and this one guards a _read_.

`fetchIssues` already threads an `AbortSignal` (`issue.store.ts:119`, `{ signal }`). Confirm a
superseded in-flight request is aborted; if it is not, a slow early keystroke can resolve after a
fast later one and paint stale results. If aborting is not already handled by the existing
plumbing, ordering must be enforced some other way — do not ship last-write-wins by luck.

### 3B.3 — Clear on navigation

D3 requires the term to clear on navigation. The store is keyed by `viewId`, which already prevents
a term bleeding between two views. Additionally clear the current view's term on unmount of the
Views page so returning to the same view starts clean.

## Verification — behavioral, not just compiled

Run in a dev server against a workspace with at least two projects and >100 work items:

- [ ] Typing a name fragment narrows every layout: List, Board, Calendar, Spreadsheet, Timeline
- [ ] `PLANE-79` (a real identifier) resolves to that single item
- [ ] `79` alone matches items whose number is 79
- [ ] A project identifier alone lists that project's items
- [ ] Clearing the box restores the full list
- [ ] Searching, then scrolling to trigger "load more", returns **more matching items** — never
      unmatched ones (this is the cursor test; it is the one most likely to fail)
- [ ] The result count shown by the UI matches the number of rows rendered
- [ ] Switching layout while a term is active keeps the term and the narrowed set
- [ ] **With a term active, opening the view as a different member shows the unfiltered view** —
      the B2 guard. Confirm no saved-view PATCH fires while typing (check the network tab).
- [ ] Navigating away and back clears the term
- [ ] A locked view still shows and honors the search box
- [ ] A term matching nothing renders the layout's normal empty state, not a blank frame or a
      spinner that never resolves — check List, Board and Spreadsheet at minimum
- [ ] With "show sub-issues" off, a matching sub-issue stays hidden. Search composes with the
      display filters by AND, same as every other filter; confirm this rather than assume it,
      and record the observed behavior in the PR so it is a decision and not a surprise

## Success criteria

- [ ] `pnpm check` clean
- [ ] All behavioral checks above pass
- [ ] Every edit to an existing file is a fenced `The1Studio fork (views-search)` block
- [ ] `git diff --stat` shows no edit to any `@plane/*` package and no new core signature change

## Do not fix in this phase

`header.tsx:117-120` computes `currentLayoutFilters` from
`ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions[layout]`, which is `undefined` for Board,
Calendar and Timeline. It is a real pre-existing defect (plan.md § "Adjacent defect observed") and
the fix is a one-line swap to the already-exported `GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS` — but it is
unrelated to search and belongs in its own change with its own review. Leave it, and make sure it
is named in the PR description so it is not lost.
