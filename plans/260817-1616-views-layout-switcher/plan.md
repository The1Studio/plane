# Views Tab — Multi-Layout Switcher

**Goal:** Add the 5-layout switcher (List, Board, Calendar, Spreadsheet, Timeline) to the
workspace **Views** tab (`/:workspaceSlug/workspace-views/:globalViewId`), matching what the
project **Work Items** tab already offers.

**Created:** 2026-08-17 · **Branch base:** `company-main` · **Fork:** The1Studio/plane

---

## Resolved decisions

| #   | Decision                | Resolution                                                                                                          |
| --- | ----------------------- | ------------------------------------------------------------------------------------------------------------------- |
| D1  | Layout scope            | **All 5 layouts** — List, Board, Calendar, Spreadsheet, Timeline                                                    |
| D2  | Server-side grouping    | **New `views_ext` Django app** — zero core Python edits                                                             |
| D3  | Group-by set            | **State group, Priority, Project, Labels, None** — mirrors Plane's own `profile_issues` set                         |
| D4  | Fork isolation strategy | New `packages/views-ext/` owns all fork logic; core files carry only thin fenced delegations                        |
| D5  | Timeline bulk date-drag | Fall back to per-item `updateIssue`; the project-scoped bulk endpoint is not reachable workspace-wide (see Phase 5) |

D4 and D5 follow directly from `docs/FORK.md` and from code constraints, not from preference —
rationale is recorded in the phase files that own them.

---

## Prior art — what already exists (do NOT rebuild)

This gate is load-bearing. **Upstream already built the entire UI seam**; it is stubbed out in CE.
The feature is filling two stubs plus one backend endpoint — not building a layout system.

| Thing                                              | Where                                                                                                                | Status                                                    |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Layout switcher UI component                       | `apps/web/core/components/issues/issue-layouts/filters/header/layout-selection.tsx`                                  | **Exists**, generic, takes `layouts: EIssueLayoutTypes[]` |
| Layout icons (all 5)                               | `apps/web/core/components/issues/issue-layouts/layout-icon.tsx`                                                      | **Exists**, all 5 cases                                   |
| Switcher already mounted in the Views header       | `apps/web/app/(all)/[workspaceSlug]/(projects)/workspace-views/header.tsx:155` renders `<GlobalViewLayoutSelection>` | **Exists** — no header edit needed                        |
| Layout dispatch already mounted                    | `apps/web/core/components/views/helper.tsx:55` falls through to `<WorkspaceAdditionalLayouts>`                       | **Exists** — no dispatch edit needed                      |
| **The two stubs that make it all no-op**           | `apps/web/ce/components/views/helper.tsx` — both return `<></>`                                                      | **THE seam to fill**                                      |
| List / Board roots for a _workspace-level_ store   | `list/roots/profile-issues-root.tsx`, `kanban/roots/profile-issues-root.tsx`                                         | **Exist** (~35 lines each) — direct templates             |
| `getGroupByColumns` workspace-level mode           | `issue-layouts/utils.tsx:65` — `isWorkspaceLevel()` already lists `EIssuesStoreType.GLOBAL`                          | **Exists**                                                |
| Global-store issue actions                         | `apps/web/core/hooks/use-issues-actions.tsx:69` — `case EIssuesStoreType.GLOBAL`                                     | **Exists**                                                |
| Global-store quick actions                         | `issue-layouts/quick-action-dropdowns/all-issue.tsx`                                                                 | **Exists**                                                |
| Cross-project **grouped** pagination on the server | `apps/api/plane/app/views/workspace/user.py:167-200` (`WorkspaceUserProfileIssuesEndpoint`)                          | **Exists** — line-for-line template                       |
| Grouping helper trio                               | `issue_queryset_grouper`, `issue_group_values`, `issue_on_results`                                                   | **Exist**, shared, already used by 2+ endpoints           |
| Grouped pagination primitive                       | `apps/api/plane/utils/paginator.py:654` — `paginate(group_by_field_name=…, group_by_fields=…)`                       | **Exists**, generic                                       |
| Global store grouping infra                        | `WorkspaceIssues extends BaseIssuesStore` — inherits `groupedIssueIds`, group pagination                             | **Exists**                                                |

**Negative results — searched scope, stated explicitly:**

- Zero calendar or gantt roots for any workspace-level store across
  `apps/web/core/components/issues/issue-layouts/{calendar,gantt}/**` — only project, cycle,
  module and project-view roots exist. Calendar and Timeline have **no** cross-project precedent.
- Zero `group_by` handling in `WorkspaceViewIssuesViewSet.list`
  (`apps/api/plane/app/views/view/base.py:214-250`) — it calls `self.paginate()` with no grouping
  kwargs. Searched the whole class body.
- Zero `kanban`/`calendar`/`gantt_chart` keys under `ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions`
  (`packages/constants/src/issue/filter.ts:170-204`) — only `spreadsheet` and `list`, and the
  `list` entry carries no `group_by` array.

---

## The three real blockers

Everything else is assembly. These are the only places where new thinking is required.

### B1 — Query params are hardcoded to Spreadsheet

`apps/web/core/store/issue/workspace/filter.store.ts:101`

```ts
const filteredParams = handleIssueQueryParamsByLayout(EIssueLayoutTypes.SPREADSHEET, "my_issues");
```

Every sibling store (cycle, module, archived, profile) passes
`userFilters?.displayFilters?.layout` instead. Until this is layout-aware, switching layout
changes the rendered component but **not** the request — `group_by` is never sent, so Board
would always show one column. Owned by **Phase 2**.

### B2 — `@plane/constants` is sealed, and its `my_issues` table is missing 3 layouts

`handleIssueQueryParamsByLayout` derives the param list from
`ISSUE_DISPLAY_FILTERS_BY_PAGE[viewType].layoutOptions[layout]`. For `my_issues` only
`spreadsheet` and `list` exist, so `layoutOptions["kanban"]` is `undefined` → the param builder
throws, and the Views header's Display dropdown
(`workspace-views/header.tsx:119`) resolves `currentLayoutFilters` to `undefined`.

`docs/FORK.md` forbids editing `@plane/*` in place, and `plane-isolation-audit` flags it.
Resolution: `packages/views-ext/` owns a fork-side layout-options table and param builder for
global views; the core store delegates to it in one fenced line. Owned by **Phase 2**.

### B3 — Timeline hard-requires a route `:projectId` that Views does not have

`apps/web/core/components/issues/issue-layouts/gantt/base-gantt-root.tsx:102`

```ts
issues.updateIssueDates(workspaceSlug.toString(), updates, projectId.toString());
```

On `/workspace-views/:globalViewId` there is no `:projectId` route param, so this throws on the
first bar drag. Note the _other_ Gantt write at line 90 already uses `issue.project_id` per item
and is fine. Owned by **Phase 5** (D5).

Calendar is **not** a blocker of this class: its fetch already passes `before`/`after` +
`groupedBy: target_date` (`base-calendar-root.tsx:90-104`) and its drag handler already takes a
per-issue `issueProjectId`. Its only gaps are the `CalendarStoreType` union and server support
for the date-range params. Owned by **Phase 4**.

---

## Fork-isolation strategy (D4)

Verified against `.claude/scripts/plane-classify-path.cjs` — the classifier that
`plane-isolation-audit` and `company-main-ci.yml` mirror.

| Path                                 | Classifier verdict               | Notes                                                                |
| ------------------------------------ | -------------------------------- | -------------------------------------------------------------------- |
| `apps/api/plane/views_ext/**`        | `custom-app` **once registered** | Requires adding `views_ext` to the `forkApps` array — see below      |
| `packages/views-ext/**`              | `custom-package`                 | Auto-classified by the `-ext` suffix rule; no registration needed    |
| `apps/api/plane/settings/common.py`  | touch-point 1                    | Append-only                                                          |
| `apps/api/plane/urls.py`             | touch-point 2                    | Append-only                                                          |
| `apps/web/package.json`              | touch-point 6                    | Append-only                                                          |
| Core web files listed in Phase 2/4/5 | `core` → flagged                 | Documented exceptions; must be added to `docs/FORK.md` — see Phase 6 |

**`forkApps` registration is not optional and not cosmetic.**
`.claude/skills/_shared/references/fork-convention.md` states that the `forkApps` array _also_
drives `.claude/scripts/plane-fork-test-paths.py`, which is what `company-main-ci.yml` uses to
pick pytest paths. An app missing from `forkApps` is **both misclassified as core AND silently
untested in CI**. Phase 1 owns adding `views_ext` to that array, and Phase 6 owns the
`docs/FORK.md` mirror update.

**Core-edit minimisation rule for every phase:** a core file may only ever gain a fenced
delegation to `@plane/views-ext` — never fork logic inline. Fence marker for this feature:

```
// The1Studio fork (views-layouts)
```

`apps/web/ce/components/views/helper.tsx` is the sanctioned exception class: `docs/FORK.md`
already lists `apps/web/ce/components/issues/issue-layouts/additional-properties.tsx` as
"the `ce/` stub seam … the intended injection point". This feature uses the identical pattern.

---

## Phases

Phase files are self-contained and pointer-addressable — hand an implementer the path, not the
contents.

| Phase | File                                                           | Deliverable                                                        | Effort |
| ----- | -------------------------------------------------------------- | ------------------------------------------------------------------ | ------ |
| 1     | [`phase-1-backend-views-ext.md`](phase-1-backend-views-ext.md) | `views_ext` Django app: grouped workspace-issues endpoint          | M (3d) |
| 2     | [`phase-2-frontend-package.md`](phase-2-frontend-package.md)   | `packages/views-ext/`: layout options, param builder, layout roots | M (3d) |
| 3     | [`phase-3-wire-ce-seam.md`](phase-3-wire-ce-seam.md)           | Fill the two `ce/` stubs → List + Board + Spreadsheet live         | S (1d) |
| 4     | [`phase-4-calendar.md`](phase-4-calendar.md)                   | Calendar layout (date-range fetch both ends)                       | M (3d) |
| 5     | [`phase-5-timeline.md`](phase-5-timeline.md)                   | Timeline layout + B3 date-drag resolution                          | M (3d) |
| 6     | [`phase-6-docs-propagation.md`](phase-6-docs-propagation.md)   | `docs/FORK.md` exception table, convention mirror, propagation     | S (1d) |

**Critical path:** 1 → 2 → 3, then 4 and 5 in parallel, then 6.
**Total:** ~14 days sequential; ~11 with 4∥5.

**First shippable increment is end of Phase 3** — switcher + List + Board + Spreadsheet, fully
grouped. Phases 4 and 5 are additive and can be deferred without leaving anything half-built.

---

## Contract — pinned before any parallel work (`rules/contract-first-integration.md`)

Phases 1 and 2 sit on opposite sides of an HTTP boundary and are implemented independently.
This contract is the SSOT; both phase files link here rather than restating it.

**Endpoint**

```
GET /api/views-ext/workspaces/<str:slug>/issues/
```

**Request params** — the existing workspace-issues param set, plus:

| Param              | Type             | Values                                                    | Notes                                             |
| ------------------ | ---------------- | --------------------------------------------------------- | ------------------------------------------------- |
| `group_by`         | string \| absent | `state__group` · `priority` · `project_id` · `labels__id` | Absent ⇒ flat list, identical to today's response |
| `sub_group_by`     | string \| absent | same set                                                  | Board sub-grouping; absent ⇒ single swimlane      |
| `before` / `after` | `YYYY-MM-DD`     | —                                                         | Calendar date-range window (Phase 4)              |
| `cursor`           | string           | `<page_size>:<page>:<offset>`                             | Unchanged from core paginator                     |

`group_by` values are **server field paths**, matching what `EIssueGroupByToServerOptions`
already emits — not UI labels. Any other value ⇒ `400`, never a silent flat fallback
(`rules/development-principles.md` § Errors Over Silent Fallbacks).

**Response** — byte-identical in shape to `WorkspaceUserProfileIssuesEndpoint`. Grouped:

```jsonc
{
  "grouped_by": "priority",
  "sub_grouped_by": null,
  "results": {
    "urgent": [
      /* TIssue[] */
    ],
    "high": [],
    "none": [],
  },
  "total_count": 468,
  "next_cursor": "100:1:0",
  "prev_cursor": "100:-1:0",
  "next_page_results": true,
  "prev_page_results": false,
  "total_pages": 5,
  "count": 100,
  "extra_stats": null,
}
```

Ungrouped: `results` is a `TIssue[]`, `grouped_by` is `null`. Both already parse in
`BaseIssuesStore.onfetchIssues` — no store-side response handling is being invented.

**Field casing is snake_case throughout**, matching every other Plane endpoint.

---

## Risk Assessment

| Risk                                                                         | L (1-5) | I (1-5) | Score  | Mitigation                                                                                              |
| ---------------------------------------------------------------------------- | ------- | ------- | ------ | ------------------------------------------------------------------------------------------------------- |
| B3 Timeline date-drag has no clean workspace-wide answer                     | 4       | 3       | **12** | Phase 5 ships per-item `updateIssue` fallback; Timeline is last, so a defer costs nothing already built |
| Core-edit set grows past the fenced minimum during implementation            | 3       | 4       | **12** | Every phase's success criteria run `plane-isolation-audit`; core files may only gain delegations        |
| `forkApps` registration forgotten → app misclassified **and** untested in CI | 3       | 4       | **12** | Explicit Phase 1 step + Phase 6 mirror check; both list it as a success criterion                       |
| Grouping across 12 projects is slow at 468+ items                            | 3       | 3       | 9      | Reuse the profile endpoint's exact annotate/prefetch chain; measure before optimising                   |
| Calendar `before`/`after` needs param plumbing on both ends                  | 3       | 2       | 6      | Contract above pins it up front; Phase 1 implements it even though Phase 4 consumes it                  |
| Upstream refactors the `ce/` stub signature on a future rebase               | 2       | 3       | 6      | Stub bodies are 3-line delegations; re-point and move on                                                |
| `pnpm check` fails on the new workspace package                              | 2       | 2       | 4      | Copy `packages/workload-ext/` tsconfig + package.json verbatim                                          |

No risk scores ≥ 15. The three 12s are all mitigated by ordering — the riskiest work (Timeline)
is last and additive.

---

## Timeline

| Phase                   | Effort                   | Notes                                                                          |
| ----------------------- | ------------------------ | ------------------------------------------------------------------------------ |
| 1 — Backend `views_ext` | M (3d)                   | Blocks 2 only on the contract, which is pinned above → can start same day as 2 |
| 2 — Frontend package    | M (3d)                   | Blocks 3                                                                       |
| 3 — Wire `ce/` seam     | S (1d)                   | **First shippable increment**                                                  |
| 4 — Calendar            | M (3d)                   | Parallel with 5                                                                |
| 5 — Timeline            | M (3d)                   | Parallel with 4; owns B3                                                       |
| 6 — Docs + propagation  | S (1d)                   | After all code lands                                                           |
| **Total**               | **~14d** (~11d with 4∥5) | Critical path: 1 → 2 → 3 → (4∥5) → 6                                           |

---

## Verification (every phase)

```bash
pnpm check                                   # TS across the monorepo
cd apps/api && python manage.py check
cd apps/api && python manage.py makemigrations --check --dry-run
```

Plus `plane-isolation-audit` on the working tree before every PR. The migration check must stay
clean: `views_ext` adds **no models**, so it must produce no migrations — a pending migration
means a core model was touched, which D2 forbids.
