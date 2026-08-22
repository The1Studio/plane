# Phase 2 — Fork package: search state, param widening, input component

**Parent plan:** [`plan.md`](plan.md) · **Depends on:** nothing · **Parallel-safe with:** Phase 1

## Goal

`packages/views-ext/` gains everything the Views-tab search needs on the client: an ephemeral
per-view search store, the type widening that lets `search` reach the request, and the search input
component. Nothing outside `packages/views-ext/` is touched — Phase 3 does the wiring.

## Pinned contract (shared with Phase 1)

```
Query parameter name:  search
Type:                  string
Semantics:             empty or absent  ->  no filtering applied
```

The emitted param name must be exactly `search`. Phase 1 implements the server half.

## File ownership

This phase owns `packages/views-ext/**` and nothing else:

- `packages/views-ext/package.json`
- `packages/views-ext/src/search-store.ts` (new)
- `packages/views-ext/src/search-params.ts` (new)
- `packages/views-ext/src/search-input.tsx` (new)
- `packages/views-ext/src/index.ts`

## Leaf 2A — Search store, types, and param widening (~2h)

### 2A.1 — Package dependencies

`packages/views-ext/package.json` currently depends only on `@plane/constants` and `@plane/types`.
Adding a mobx store and a React component needs the same dependency set
`packages/workload-ext/package.json` already carries. Copy that shape: add `@plane/propel`,
`@plane/utils`, `@plane/hooks`, `mobx`, `mobx-react`, `react`, `react-dom` to `dependencies`
(all `workspace:*` or `catalog:` exactly as workload-ext declares them), `@types/react` and
`@types/react-dom` to `devDependencies`, and the `peerDependencies` block for react.

Verify `@plane/hooks` is how `useOutsideClickDetector` is published — core imports it as
`import { useOutsideClickDetector } from "@plane/hooks"`
(`apps/web/core/components/pages/list/search-input.tsx:9`). If that package is not already a
workspace dependency elsewhere in `packages/`, prefer inlining a small outside-click effect in
2B over adding a new package edge.

### 2A.2 — `src/search-store.ts`

An observable store keyed by view id. Model it on `packages/workload-ext/src/store.ts` for class
shape and on `apps/web/ce/store/root.store.ts:42` for how it will be instantiated.

```ts
export interface IViewsSearchStore {
  getSearchQuery(viewId: string): string;
  setSearchQuery(viewId: string, query: string): void;
  clearSearchQuery(viewId: string): void;
}
```

Requirements, each load-bearing:

- **Ephemeral by construction.** The observable is a plain in-memory `Record<string, string>`.
  No `localStorage`, no service call, no serialization. This is what makes D3 true and B2 safe.
- **Keyed by `viewId`**, so switching between two saved views does not carry a term across.
- **`getSearchQuery` returns `""` for an unknown view id**, never `undefined` — the consumer
  treats empty as "no filter", and `undefined` would force a null check at every call site.
- Do **not** give the store a reference to the issue store or trigger any fetch. It holds a string.
  Phase 3 owns the re-fetch, so this stays testable and free of a circular store dependency.

### 2A.3 — `src/search-params.ts`

Resolves blocker **B1** (plan.md): `search` is not a member of the sealed `TIssueParams`.

```ts
import type { TIssueParams } from "@plane/types";

/** The1Studio fork (views-search) — `TIssueParams` widened by the one param the fork adds.
 *  Written as a union with the sealed type so that if upstream ever adds `search` to
 *  `TIssueParams`, this collapses to `TIssueParams` harmlessly instead of conflicting. */
export type TViewsExtIssueParams = TIssueParams | "search";

export function withGlobalViewSearch(
  params: Partial<Record<TIssueParams, string | boolean | string[]>>,
  searchQuery: string
): Partial<Record<TViewsExtIssueParams, string | boolean | string[]>>;
```

Behavior:

- A blank or whitespace-only `searchQuery` returns `params` **unchanged** — the key is absent, not
  present-and-empty. This is the client half of the contract's "empty ≡ absent" rule; sending
  `?search=` would work given Phase 1's guard, but omitting it keeps request URLs and any request
  de-duplication clean.
- Otherwise returns a new object with `search` set to the trimmed term. Never mutates the input —
  `getAppliedFilters` callers in core assume a fresh object.
- Keep the function pure and free of store imports. Phase 3 supplies the term.

Match the file-header comment style of the existing `query-params.ts`: state what upstream
constraint forced this and point at plan.md § B1.

### 2A.4 — Export from `src/index.ts`

Append `export * from "./search-store";`, `export * from "./search-params";`,
`export * from "./search-input";`. Keep the existing exports untouched.

## Leaf 2B — `src/search-input.tsx` (~2h)

A controlled expand-on-click search input implementing D4.

```ts
type Props = {
  searchQuery: string;
  updateSearchQuery: (val: string) => void;
  placeholder?: string;
};
export function WorkItemSearchInput(props: Props): JSX.Element;
```

Interaction, mirroring `apps/web/core/components/pages/list/search-input.tsx:19-87`:

- Collapsed: a ghost `IconButton` with `SearchIcon` from `@plane/propel`.
- Click expands to a `w-64` bordered input and focuses it.
- `Escape` clears a non-empty term; on an already-empty term it collapses and blurs.
- Outside click collapses **only when the term is empty**, so a user clicking into the list does not
  lose an active search.
- An explicit close button clears the term and collapses.
- `placeholder` defaults to a work-item-appropriate string, not `"Search pages"`.

**Required file-header comment** (per `rules/search-before-you-build.md` — a deliberate parallel
implementation must say why it exists):

> The1Studio fork (views-search). Deliberately parallel to core's `PageSearchInput`
> (`apps/web/core/components/pages/list/search-input.tsx`), which implements the same interaction.
> It is not reused because a file under `packages/` cannot import from `apps/web/core/` — that
> package-graph edge does not exist — and because its placeholder is hardcoded to "Search pages".
> See plan.md § D6. Do not "de-duplicate" these without first resolving the dependency direction.

The component is presentational and fully controlled: no store import, no fetch, no debounce. Phase
3 owns all three. That keeps this file renderable in isolation and free of the store cycle.

## Success criteria

- [ ] `pnpm --filter @plane/views-ext build` succeeds
- [ ] `pnpm --filter @plane/views-ext check:types` clean
- [ ] `pnpm check` clean at the repo root
- [ ] `withGlobalViewSearch(params, "")` and `withGlobalViewSearch(params, "   ")` both return an
      object with **no** `search` key
- [ ] `withGlobalViewSearch` does not mutate its input object
- [ ] `getSearchQuery("unknown-id")` returns `""`
- [ ] `WorkItemSearchInput` imports nothing from `apps/`
- [ ] `git diff --name-only` for this phase touches only `packages/views-ext/**`

## Notes

- `packages/views-ext/**` is auto-classified `custom-package` by the `-ext` suffix rule in
  `.claude/scripts/plane-classify-path.cjs`. No registry edit, no `FORK.md` row for these files
  beyond the package subsection Phase 4 updates.
- Do not touch `layout-options.ts` or `query-params.ts`. Search is orthogonal to layout options —
  it applies to every layout identically, so it does not belong in the per-layout tables.
