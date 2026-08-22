# Views Tab — Work-Item Search

**Goal:** Add a work-item text search to the workspace **Views** tab
(`/:workspaceSlug/workspace-views/:globalViewId`). The search is a server-side filter on the
fork's `views_ext` endpoint, so it narrows the result set for **every** layout — List, Board,
Calendar, Spreadsheet, Timeline — not just the rows already loaded on screen.

**Created:** 2026-08-22 · **Branch base:** `company-main` · **Fork:** The1Studio/plane
**Builds on:** `plans/260817-1616-views-layout-switcher/` (the switcher this search sits beside)

---

## Resolved decisions

| #   | Decision            | Resolution                                                                                                             |
| --- | ------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| D1  | Surface scope       | **Whole Views tab, all 5 layouts.** One header control; search is a server filter, so it applies uniformly.            |
| D2  | Match rule          | **Name + work-item number + project identifier**, via core's existing `search_issues()` helper. `PLANE-79` resolves.   |
| D3  | Persistence         | **Ephemeral.** Term lives in a fork-owned mobx store, cleared on navigation. Never written to the saved view.          |
| D4  | Placement           | **Header toolbar, expanding search icon** in `Header.RightItem`, left of the layout switcher.                          |
| D5  | Search execution    | **Server-side.** Forced by the code, not chosen — see "Why server-side is not a preference" below.                     |
| D6  | Component ownership | **Fork-owned `WorkItemSearchInput` in `packages/views-ext/`**, not a reuse of core's `PageSearchInput` — see D6 below. |
| D7  | Profile pages       | **Out of scope.** The sibling endpoint gets a reusable helper but no wiring. See "Deliberately not in scope".          |

D1–D4 were decided by the user. D5, D6 and D7 follow from code constraints recorded below.

### D5 — why server-side is not a preference

`GET /api/views-ext/workspaces/<slug>/issues/` is cursor-paginated with `per_page` defaulting to
1000 and the frontend loading incrementally (`WorkspaceIssues.fetchNextIssues`,
`apps/web/core/store/issue/workspace/issue.store.ts:138`). A client-side filter over
`groupedIssueIds` would search only the pages already fetched and silently report zero matches for
an item on page 2. There is no correct client-side variant of this feature, so no option was
offered.

### D6 — why a fork-owned input rather than reusing `PageSearchInput`

`apps/web/core/components/pages/list/search-input.tsx:19-87` implements exactly the
expand-on-click / `Escape`-to-clear / outside-click-collapse interaction D4 asks for, and its props
(`{ searchQuery, updateSearchQuery }`) are fully controlled with no store coupling. It is still not
reusable here, for a structural reason rather than a stylistic one:

- **Dependency direction.** Per D4 of the switcher plan, fork logic lives in `packages/views-ext/`
  and core files carry only thin fenced delegations. A file under `packages/` cannot import from
  `apps/web/core/` — that edge does not exist and adding it would invert the package graph.
- **Its placeholder is hardcoded** (`placeholder="Search pages"`, line 66), so even a core-side
  reuse needs an additive prop edit to a Pages-module component.

The fork component is built on the same sealed primitives the core one uses — `@plane/propel`
`IconButton`/`SearchIcon`/`CloseIcon`, `@plane/hooks` `useOutsideClickDetector`, `@plane/utils`
`cn` — all importable from a package. `packages/workload-ext/package.json` is the precedent for a
fork package carrying `react` + `mobx` + `@plane/propel`.

This is a deliberate parallel implementation, so per `rules/search-before-you-build.md` the reason
above is restated as a comment in the new file. Do not silently "de-duplicate" it later without
resolving the dependency direction first.

---

## Prior art — what already exists (do NOT rebuild)

This gate is load-bearing. Most of this feature is assembly; only two places need new thinking.

| Thing                                                | Where                                                                                   | Status                                                     |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Canonical work-item search query                     | `apps/api/plane/utils/issue_search.py:14-24` — `search_issues(query, queryset)`         | **Exists**, generic, already used by 3 call sites          |
| The exact D2 match rule                              | same file: `name__icontains`, whole-int `sequence_id`, `project__identifier__icontains` | **Exists** — D2 is a reuse, not a new query design         |
| Endpoint to add the param to                         | `apps/api/plane/views_ext/views.py:170` `GroupedWorkspaceViewIssuesEndpoint`            | **Exists** — fork-owned, no core Python edit needed        |
| Queryset already permission-scoped before pagination | `views.py:191-217` `_get_project_permission_filters()`                                  | **Exists** — search filters an already-safe queryset       |
| Fork package for Views-tab logic                     | `packages/views-ext/`                                                                   | **Exists** — 3 files, D4 isolation already established     |
| Fork package carrying react + mobx + propel          | `packages/workload-ext/package.json`                                                    | **Exists** — the dependency-set template for Phase 2       |
| `ce/` seam for registering a fork mobx store         | `apps/web/ce/store/root.store.ts:9,21,42` (`workloadStore`)                             | **Exists** — line-for-line template for the search store   |
| Fenced fork delegation point for query params        | `apps/web/core/store/issue/workspace/filter.store.ts:26,119` (`getAppliedFilters`)      | **Exists** — already a documented fork exception           |
| Views-tab header with a `Header.RightItem` group     | `.../workspace-views/header.tsx:152-186`                                                | **Exists** — mount point for D4                            |
| Expand/collapse search interaction to model on       | `apps/web/core/components/pages/list/search-input.tsx:19-87`                            | **Exists** — the model, not the import (D6)                |
| Re-fetch-on-filter-change path                       | `filter.store.ts:277` → `fetchIssuesWithExistingPagination(slug, viewId, "mutation")`   | **Exists** — search reuses it verbatim                     |
| `views_ext` registered for CI test selection         | `.claude/skills/_shared/references/fork-convention.md:65` `forkApps`                    | **Exists** — no registry edit needed this time             |
| Backend test harness for this app                    | `apps/api/plane/views_ext/tests/test_grouped_view_issues.py`                            | **Exists** — `TransactionTestCase` + `APIClient` + helpers |

### Negative results — searched scope, stated explicitly

- **No free-text search reaches this tab today, by any route.** Zero `search` / `q` / `query`
  parameter across both endpoint classes in `apps/api/plane/views_ext/views.py` (all 538 lines) and
  its `urls.py`.
- **The rich-filter bar cannot express one either.** `WORK_ITEM_FILTER_PROPERTY_KEYS`
  (`packages/types/src/view-props.ts:96-112`) is states, priority, dates, assignee, mention,
  created_by, subscriber, label, cycle, module, project, created_at, updated_at — no text field.
  Its backend twin `IssueFilterSet` (`apps/api/plane/utils/filters/filterset.py:124-176`) declares
  the same set.
- **`search` is not a member of `TIssueParams`** (`packages/types/src/view-props.ts:63-91`) and
  there is no `name`/`search` key on `IIssueFilterOptions` (same file, 131-147). Both live in
  sealed `@plane/*` packages. This is blocker **B1** below.
- **No reusable issue-search box exists in `apps/web/`.** No `useIssuesSearch` hook and no
  `SearchInput` component under that name anywhere in the tree. The only issue text search is the
  command palette (`apps/web/core/components/power-k/**`), a modal keyboard surface with no
  extractable input component. The search box on `workspace-views/page.tsx:33-41` searches **view
  names**, client-side, and is unrelated.
- Core's legacy `name` → `name__icontains` filter (`apps/api/plane/utils/issue_filters.py:203-206`)
  _is_ reachable by the endpoint via `issue_filters()`, but nothing in the frontend ever sends it,
  and name-only matching was rejected as D2.

---

## The two real blockers

### B1 — `search` is not expressible in the sealed param types

`getAppliedFilters` (`apps/web/core/store/issue/workspace/filter.store.ts:107-139`) returns
`Partial<Record<TIssueParams, …>>`, and `TIssueParams` has no `search` member. `docs/FORK.md`
forbids editing `@plane/*` in place, and `plane-isolation-audit` flags it.

**Resolution:** `packages/views-ext/` owns the widened type and a `withGlobalViewSearch()` wrapper
that merges the term in and does the widening internally. The core store's edit stays a single
fenced delegation line — the same shape as the existing `getGlobalViewQueryParamsByLayout`
delegation on line 119. Owned by **Phase 2 + Phase 3**.

### B2 — the search term must not travel with the persisted filters

D3 says ephemeral, and the existing filter path is the opposite: `updateFilters`
(`filter.store.ts:230-277`) writes into the observable `filters[viewId]`, persists to local storage
for static views, and PATCHes saved views server-side. A term routed through it would leak into a
**shared** workspace view and change what other members see.

**Resolution:** a separate fork-owned observable store keyed by `viewId`, registered on the root
store via the `ce/` seam, read at param-assembly time only. It is never serialized and never
reaches `updateFilters`. Owned by **Phase 2 + Phase 3**.

Everything else — the query itself, permission scoping, pagination, re-fetch, the header slot — is
assembly over the prior art above.

---

## Fork-isolation strategy

Verified against `.claude/scripts/plane-classify-path.cjs`, the classifier that
`plane-isolation-audit` and `company-main-ci.yml` mirror.

| Path                                                  | Classifier verdict  | Notes                                                    |
| ----------------------------------------------------- | ------------------- | -------------------------------------------------------- |
| `apps/api/plane/views_ext/**`                         | `custom-app`        | Already in `forkApps`; tests already selected by CI      |
| `packages/views-ext/**`                               | `custom-package`    | Auto-classified by the `-ext` suffix rule                |
| `apps/web/ce/store/root.store.ts`                     | `ce/` seam          | Established injection point (`workloadStore` precedent)  |
| `apps/web/core/store/issue/workspace/filter.store.ts` | core-edit exception | **Already** a documented Views exception; one added line |
| `.../workspace-views/header.tsx`                      | core-edit exception | **New** row in the `FORK.md` Views table — Phase 4       |

Every new core-side edit is fenced `The1Studio fork (views-search)`. No new Django app, no new
migration, no core model change, no `@plane/*` edit.

---

## Deliberately not in scope

- **The "Your work" profile pages** (`/profile/:userId/{assigned,created,subscribed}`). They share
  the sibling endpoint `GroupedWorkspaceUserProfileIssuesEndpoint` (`views.py:349`) and the mirrored
  `PROFILE` store, so the same search would drop in cheaply. D1 scoped this out. Phase 1 still
  extracts the backend search as a module-level helper so adopting it there later is a one-line
  change rather than a copy — but no profile wiring ships here.
- **Description matching.** Rejected as D2: no core precedent and an unindexed scan of
  `description_stripped` on a busy workspace is a performance question this plan does not answer.
- **Semantic search.** `ai_ext/` has BGE-M3 embeddings over issues (`ai_ext/views/search.py:43`),
  but it is a POST RAG endpoint returning a generated answer plus citations — not a navigable,
  paginated, groupable result list. Wrong shape for this seam.

---

## Adjacent defect observed — flagged, not fixed

`.../workspace-views/header.tsx:117-120` computes:

```ts
const layout = activeLayout ?? EIssueLayoutTypes.SPREADSHEET;
return ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions[layout];
```

`ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions` defines only `spreadsheet` and `list`
(`packages/constants/src/issue/filter.ts:170-204`), so `currentLayoutFilters` is `undefined`
whenever the active layout is Board, Calendar or Timeline — and the Display dropdown below it
renders against `undefined`. This is exactly blocker **B2 of the switcher plan**, which was fixed in
the filter store but evidently not in this header.

It is pre-existing, unrelated to search, and Phase 3 touches this file — so per
`rules/coding-guidelines.md` §3 it is **reported, not silently repaired**. `GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS`
is already exported from `packages/views-ext` and is the drop-in fix; it wants its own change so it
gets its own review and its own `FORK.md` row.

---

## Phases

| Phase                                            | File                          | Owns                                                      |
| ------------------------------------------------ | ----------------------------- | --------------------------------------------------------- |
| 1 — Backend `search` param                       | `phase-1-backend-search.md`   | `views_ext/views.py` + its tests                          |
| 2 — Fork package: search state, types, component | `phase-2-package-search.md`   | `packages/views-ext/**`                                   |
| 3 — Wire store + header                          | `phase-3-wire-header.md`      | `ce/store/root.store.ts`, `filter.store.ts`, `header.tsx` |
| 4 — Docs, isolation audit, propagation           | `phase-4-docs-propagation.md` | `docs/FORK.md`, `CLAUDE.md`, sibling-repo issues          |

Phases 1 and 2 are independent and may run in parallel — disjoint trees (`apps/api/**` vs
`packages/**`), no shared file, no shared declaration. Phase 3 depends on both. Phase 4 depends on
Phase 3.

**Contract pinned before any fan-out** — the one shape both parallel lanes must agree on:

```
Query parameter name:  search
Type:                  string
Semantics:             empty or absent  ->  no filtering applied (no hidden default exclusion)
Match:                 plane.utils.issue_search.search_issues(query, queryset)
Applied:               after permission scoping, before pagination
```

Phase 1 implements the server half, Phase 2 emits the client half. Neither may rename it.

---

## Risk Assessment

| Risk                                                                                          | Likelihood | Impact | Score | Mitigation                                                                                                                               |
| --------------------------------------------------------------------------------------------- | ---------- | ------ | ----- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Empty search term silently excludes rows (the "no filter means no filtering" trap)            | 3          | 5      | 15    | Contract above makes empty ≡ absent ≡ unfiltered. Phase 1 ships an explicit test asserting `?search=` returns the same set as no param.  |
| Search term leaks into a saved workspace view and changes it for every member                 | 2          | 5      | 10    | B2 resolution: term never enters `updateFilters`. Phase 3 asserts the saved-view PATCH payload is unchanged while a term is active.      |
| Stale cursor — searching while on page 3 returns a filtered slice of the old result set       | 3          | 3      | 9     | Term change routes through `fetchIssuesWithExistingPagination(..., "mutation")`, the same path a filter change uses. Phase 3.            |
| `search` widening in views-ext drifts from the sealed `TIssueParams` after an upstream rebase | 2          | 3      | 6     | Widened type is defined as `TIssueParams \| "search"`, so an upstream addition of `search` collapses harmlessly instead of conflicting.  |
| Un-debounced input fires one request per keystroke                                            | 3          | 2      | 6     | 300 ms debounce in the Phase 3 hook, with the in-flight request aborted via the existing `signal` plumbing in `fetchIssues`.             |
| Rebase conflict in `header.tsx` / `filter.store.ts`                                           | 2          | 2      | 4     | Both are already declared fork exception points; edits are single fenced lines. Phase 4 adds the `FORK.md` rows that make this expected. |

No risk scores ≥ 15 remain unmitigated.

## Timeline

| Phase                           | Effort  | Notes                                                                 |
| ------------------------------- | ------- | --------------------------------------------------------------------- |
| Phase 1: Backend `search` param | S (~3h) | Reuses `search_issues()`; most of the effort is the test class        |
| Phase 2: Fork package           | M (~4h) | Two independent leaves: state+types, then the component               |
| Phase 3: Wire store + header    | M (~4h) | Two leaves: store registration + param delegation, then header + hook |
| Phase 4: Docs + propagation     | S (~3h) | `FORK.md` rows, isolation audit, sibling-repo issues                  |
| **Total**                       | **~2d** | Critical path: (1 ∥ 2) → 3 → 4                                        |

## Verification bar

Every phase is verified by the same commands, run from the repo root:

```bash
# backend
cd apps/api && python manage.py check && python -m pytest plane/views_ext/tests/ -q
cd apps/api && python manage.py makemigrations --check --dry-run   # must report no changes

# frontend
pnpm check
pnpm --filter @plane/views-ext build

# fork isolation
node .claude/scripts/plane-classify-path.cjs $(git diff --name-only origin/company-main...HEAD)
```

The `makemigrations --check` gate is listed even though this plan adds no model, because
`company-main-ci.yml` runs it on every push and a stray import can still trip it.

## Cook handoff

```
/t1k:cook plans/260822-1102-views-workitem-search/
```
