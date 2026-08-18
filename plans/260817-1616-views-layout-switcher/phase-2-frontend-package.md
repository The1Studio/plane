# Phase 2 — `packages/views-ext`: fork-owned layout options, param builder, layout roots

**Goal:** Build every piece of fork logic the Views tab needs, in a fork-owned package, so
Phase 3 can wire it up with three-line delegations. Resolves blockers **B1** and **B2**.

**Contract:** [`plan.md`](plan.md) § Contract. **Blockers:** [`plan.md`](plan.md) § B1, B2.
**Effort:** M (~3d) · **Blocks:** Phase 3 · **Consumes:** Phase 1 at runtime (build against the contract, not against a running server).

---

## Why a package and not core files

`docs/FORK.md` § Frontend customizations: new frontend code lives in a new `packages/<name>-ext/`.
`.claude/scripts/plane-classify-path.cjs` auto-classifies any `packages/*-ext/` path as
`custom-package` via the `forkPackageSuffix` rule — **no registration step needed** (unlike the
Django app in Phase 1). Copy `packages/workload-ext/` for `package.json`, `tsconfig.json` and
build wiring; it is the working precedent in this repo.

Consumed from `apps/web` via `workspace:*` — that dependency line in `apps/web/package.json` is
touch-point 6, append-only.

## Deliverable 1 — Fork-owned layout options table (**resolves B2**)

`ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions` in `@plane/constants` has only
`spreadsheet` and `list`, and its `list` entry carries no `group_by`. `@plane/*` is sealed —
`docs/FORK.md` forbids editing it in place and `plane-isolation-audit` flags it.

Export a fork-owned table covering all five layouts. Model each entry on the corresponding
`profile_issues` entry in `packages/constants/src/issue/filter.ts` — that page is workspace-level
and cross-project, so its choices are already validated for this exact context. Per D3, the
`group_by` array is:

```ts
["state_detail.group", "priority", "project", "labels", null];
```

Do **not** widen it to `state` / `cycle` / `module`. Those are per-project (D3, and the
`plan.md` § Contract note).

Also export a `GLOBAL_VIEW_LAYOUTS: EIssueLayoutTypes[]` list — the switcher's button set, and
the single place layout availability is decided. Phases 4 and 5 append to this one array rather
than touching the switcher.

## Deliverable 2 — Layout-aware param builder (**resolves B1**)

`apps/web/core/store/issue/workspace/filter.store.ts:101` hardcodes
`handleIssueQueryParamsByLayout(EIssueLayoutTypes.SPREADSHEET, "my_issues")`. Every sibling store
(cycle, module, archived, profile) passes `userFilters?.displayFilters?.layout`. Until this is
layout-aware, switching layout re-renders the component but does not change the request, so
`group_by` never reaches the server and Board renders one column.

Export a builder that takes the active layout and returns the `TIssueParams[]` for it, reading
Deliverable 1's table. Mirror `handleIssueQueryParamsByLayout`'s logic
(`packages/utils/src/work-item/base.ts:104-133`) — same derivation from `display_filters` keys
plus `extra_options` — so behaviour stays consistent with the rest of the app.

The one-line core delegation that calls this lands in **Phase 3**, not here.

## Deliverable 3 — Layout roots for the global store · **CORRECTED 2026-08-17**

> **These roots are NEW CORE FILES, not package files.** The original plan put them in
> `packages/views-ext`; that is impossible. `BaseListRoot` / `BaseKanBanRoot` import via the `@/`
> alias (`@/hooks/store/use-issues`, `@/hooks/use-issue-layout-store`, …), which is defined only in
> `apps/web/tsconfig.json` and does not resolve from a workspace package — packages are consumed
> **by** `apps/web`, not the reverse. Verified both ways: the existing GLOBAL root
> `spreadsheet/roots/workspace-root.tsx` uses `@/` imports at lines 14-24 and lives in core, while
> `grep -rn 'from "@/"' packages/workload-ext/src/` returns zero hits.
>
> Create them as the GLOBAL-store siblings of the existing spreadsheet root, matching its naming:
>
> - `apps/web/core/components/issues/issue-layouts/list/roots/workspace-root.tsx` → `WorkspaceListRoot`
> - `apps/web/core/components/issues/issue-layouts/kanban/roots/workspace-root.tsx` → `WorkspaceKanBanRoot`
>
> **New core files are an established pattern in this fork**, not an exception invented here —
> `docs/FORK.md`'s workload table already lists three (`use-workload-estimate.ts`,
> `estimated-hours-column.tsx`, `progress-column.tsx`, each marked NEW). A new file at a path
> upstream does not use has near-zero rebase-conflict surface. Fence each with
> `// The1Studio fork (views-layouts)`; Phase 6 records both in `docs/FORK.md`.
>
> **Consequence:** this phase's "touches no core file" success criterion is void — see below.
> Phase 4 and Phase 5 roots inherit the same constraint.

Thin wrappers, one per layout. Templates (~35 lines each) — read them first:

| Layout | Template                                                                             | Notes                                                                                                                         |
| ------ | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| List   | `apps/web/core/components/issues/issue-layouts/list/roots/profile-issues-root.tsx`   | Wraps `BaseListRoot`; pass a `canEditPropertiesBasedOnProject` closure — permissions are per-project even in a workspace view |
| Board  | `apps/web/core/components/issues/issue-layouts/kanban/roots/profile-issues-root.tsx` | Wraps `BaseKanBanRoot`, same shape                                                                                            |

Use `AllIssueQuickActions` from
`apps/web/core/components/issues/issue-layouts/quick-action-dropdowns/all-issue.tsx` — it already
exists and is already global-store-aware (`storeType: EIssuesStoreType.GLOBAL`). Do not pass
`ProjectIssueQuickActions`; the profile templates use it only because they predate the global variant.

Calendar and Timeline roots are **out of scope here** — Phases 4 and 5.

## Deliverable 4 — The switcher · **data only** (corrected 2026-08-17)

`LayoutSelection`
(`apps/web/core/components/issues/issue-layouts/filters/header/layout-selection.tsx`) already
handles icons, tooltips, i18n and active-state styling for all five layouts. The circled control in
`img1.png` **is** that component — it is already rendered in the Views header at
`workspace-views/header.tsx:155` and renders empty today only because the CE stub returns `<></>`.

It hits the same `@/`-alias wall as Deliverable 3, so this phase ships **only the data**: export
`GLOBAL_VIEW_LAYOUTS: EIssueLayoutTypes[]`. Phase 3 composes
`<LayoutSelection layouts={GLOBAL_VIEW_LAYOUTS} … />` inline inside the `ce/` stub, where `@/`
resolves.

A component-injection factory (`createGlobalViewLayoutSelection(LayoutSelection)`) was considered
and **rejected** — indirection to dodge a single import, against KISS/YAGNI. Keep the package free
of React-component plumbing.

`GLOBAL_VIEW_LAYOUTS` remains the single place layout availability is declared; Phases 4 and 5
append to this one array. Start it with `LIST`, `KANBAN`, `SPREADSHEET`.

## Store-type unions — noted here, edited in Phase 3

`BaseListRoot` and `BaseKanBanRoot` type their store as a union that excludes
`EIssuesStoreType.GLOBAL`:

- `list/base-list-root.tsx:30` — `ListStoreType`
- `kanban/base-kanban-root.tsx:36` — `KanbanStoreType`

Each needs `| EIssuesStoreType.GLOBAL` added. These are core files, so the edits belong with the
other core delegations in Phase 3 — flagged here so Phase 2 does not stall on the type error when
building the roots in isolation.

## Success criteria

- [ ] `packages/views-ext/` builds standalone; `pnpm check` clean across the monorepo
- [ ] Layout options table exports entries for all 5 layouts, with the D3 `group_by` set
- [ ] `GLOBAL_VIEW_LAYOUTS` exists and is the only place layout availability is declared
- [ ] Param builder returns `group_by` in its param list for `list` and `kanban`, and omits it for `spreadsheet`
- [ ] `WorkspaceListRoot` / `WorkspaceKanBanRoot` exist as NEW core files and compile (the
      `ListStoreType` / `KanbanStoreType` union error is expected — Phase 3 fixes it)
- [ ] `node .claude/scripts/plane-classify-path.cjs packages/views-ext/src/index.ts` → `custom-package`
- [ ] Zero new imports of `@plane/constants`' `my_issues.layoutOptions` in fork code — the fork table replaces it
- [ ] ~~`plane-isolation-audit`: PASS (no core file)~~ **VOID** — corrected 2026-08-17. The audit
      correctly flags the two new core roots. Criterion is now: the audit flags **exactly** those
      two files from this phase and nothing else; Phase 6 documents them.

## Risks

| Risk                                                                   | L   | I   | Score | Mitigation                                                                                                         |
| ---------------------------------------------------------------------- | --- | --- | ----- | ------------------------------------------------------------------------------------------------------------------ |
| Fork layout table drifts from `@plane/constants` on a future rebase    | 3   | 3   | 9     | Header-comment the file with its upstream source path + the reason it exists; Phase 6 records it in `docs/FORK.md` |
| Param builder diverges from `handleIssueQueryParamsByLayout` semantics | 2   | 4   | 8     | Mirror that function's derivation exactly; do not "improve" it                                                     |
| New workspace package misconfigured (`pnpm check` fails)               | 2   | 2   | 4     | Copy `packages/workload-ext/` config verbatim                                                                      |
