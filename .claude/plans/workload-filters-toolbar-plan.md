# Workload Toolbar — Filters + Theme-Aware Rebuild

**Created:** 2026-08-12
**Branch base:** `company-main`
**Scope:** `packages/workload-ext` (isolated fork package) + `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx` (fork-owned NEW file)
**Backend changes:** none — `assignee_ids`, `project_ids`, `state_group` are already parsed and honored by `apps/api/plane/workload/views.py:88-93`.

---

## 1. Problem

Two defects, one root cause.

### 1a. No filters are reachable from the UI

`packages/workload-ext/src/WorkloadFilters.tsx` implements project + assignee multi-selects, a state-group hook, and an over-capacity checkbox. It is exported from `src/index.ts:9` and **rendered by nothing**. The only toolbar the user sees is `renderToolbar()` inlined at `WorkloadMatrix.tsx:338`, which exposes granularity + dates only.

The store already carries every filter (`selectedAssigneeIds`, `selectedProjectIds`, `selectedStateGroups`, `showOverCapacityOnly` — `store.ts:106-112`) and `fetchWorkload` already serializes them into the request (`store.ts:243-250`). The backend already validates and applies them. **The wiring gap is purely at the render layer.**

### 1b. The toolbar is not theme-aware (the screenshot)

`renderToolbar()` styles with raw Tailwind palette classes — `bg-white`, `text-gray-600`, `border-gray-200` — instead of the design-system tokens the rest of the app moved to (`@plane/propel` uses `bg-layer-1`, `border-subtle`, `text-13` — see `packages/propel/src/table/core.tsx:27`). Under the dark theme in the screenshot this produces:

| Symptom in screenshot                                                | Cause                                                                                                                                                              |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| "Day" and "Month" render as light-grey boxes that read as _disabled_ | `bg-white text-gray-600` hardcoded on inactive granularity buttons (`WorkloadMatrix.tsx:358`)                                                                      |
| Active "Week" has near-zero contrast against its neighbours          | `bg-custom-primary-100 text-custom-primary-200` — primary-on-primary pairing (`WorkloadMatrix.tsx:357`)                                                            |
| Date fields are white boxes with a browser calendar glyph            | raw `<input type="date">` (`WorkloadMatrix.tsx:373, 383`) — the native control ignores app theming and does not match Plane's date UX anywhere else in the product |

The same class of defect exists below the toolbar (capacity badge `bg-gray-100`, over-capacity pill `bg-red-100`, over-cell `bg-amber-50`, every loading/error/empty state `text-gray-*`) — in scope per the decision below.

---

## 2. Decisions (resolved with the user before drafting)

| #   | Decision                                     | Chosen                                                             | Consequence                                                                                                                                                                                                                                                                                |
| --- | -------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | How the member filter is built               | **Reuse core `MemberDropdown` via a slot prop**                    | `workload-ext` cannot import `@/components/...` — its deps are `@plane/propel`, `@plane/constants`, `@plane/types` only (`package.json:24-31`). The app-side page renders Plane's real dropdowns and injects them as `ReactNode` slots. Isolation preserved; product look matched exactly. |
| D2  | Depth of the visual fix                      | **Full toolbar rebuild + whole matrix**                            | Granularity → propel `Tabs`; dates → core `DateRangeDropdown`; every hardcoded palette class in the package → design-system tokens (toolbar, table cells, badges, pills, meta, and all four state screens).                                                                                |
| D3  | Which filters ship                           | **All of them** — member, project, state group, over-capacity-only | Member/project/state-group are server-side (refetch on change). Over-capacity-only stays client-side (`WorkloadMatrix.tsx:220`, plan D-B4) — no refetch.                                                                                                                                   |
| D4  | "Unassigned" row under a member filter       | **Hide it**                                                        | Server-side `assignee_ids` already excludes it (`assignee_id` is null, never matches a UUID). No extra request, no client-side merge-back. Selecting members returns exactly those members.                                                                                                |
| D5  | Refetch cadence for member/project dropdowns | **Refetch per selection**                                          | `onChange` fires per click, matching every other Plane filter dropdown; the matrix updates live as each name is ticked. No `onClose` batching.                                                                                                                                             |

**Slot contract** (pinned before any parallel work — `rules/contract-first-integration.md`):

```ts
// packages/workload-ext/src/WorkloadMatrix.tsx
type WorkloadMatrixProps = {
  store: IWorkloadStore;
  workspaceSlug: string;
  isAdmin?: boolean;
  /** App-side filter controls injected into the toolbar. Each is optional;
   *  a missing slot renders nothing (package stays usable standalone). */
  memberFilterSlot?: React.ReactNode;
  projectFilterSlot?: React.ReactNode;
  dateRangeSlot?: React.ReactNode;
};
```

State group + over-capacity-only are **not** slots — they are built inside the package from `@plane/constants` `STATE_GROUPS` (already a dependency) and propel primitives, because they need no app store.

---

## 3. Phases

### Phase 1 — Package: toolbar rebuild + slots + token sweep

**Owner:** single agent. **Files owned:** `packages/workload-ext/src/**` only.

| Step | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Verify                                                                                     |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1.1  | Extract `renderToolbar()` out of the `WorkloadMatrix` closure into a real `WorkloadToolbar` component in a new `src/WorkloadToolbar.tsx`. It currently reads `store`, `workspaceSlug`, and the two handlers via closure — pass them as props.                                                                                                                                                                                                                        | `pnpm --filter @plane/workload-ext check:types`                                            |
| 1.2  | Replace the hand-rolled granularity button group with propel `Tabs` (`Tabs.Root` / `Tabs.List` / `Tabs.Trigger`, `variant="contained"` — `packages/propel/src/tabs/tabs.tsx:20-38`). Keep `handleGranularityClick` semantics: set granularity **then** refetch.                                                                                                                                                                                                      | Day/Week/Month all legible in both themes; active state visibly distinct                   |
| 1.3  | Delete both `<input type="date">` blocks; render `dateRangeSlot` in their place. Keep `MAX_SPAN_DAYS` clamping **in the package** (`handleDateChange`, `WorkloadMatrix.tsx:142-164`) and expose it so the app can pass `maxDate` — the clamp must not become app-side-only logic. Export `MAX_SPAN_DAYS` and a `clampDateRange(from, to, granularity)` helper from the package.                                                                                      | Selecting a >92-day span on `day` granularity clamps, same as today                        |
| 1.4  | Render `memberFilterSlot` and `projectFilterSlot` in the toolbar.                                                                                                                                                                                                                                                                                                                                                                                                    | Slots appear; omitting them renders nothing (no empty boxes)                               |
| 1.5  | Build the state-group filter **inside** the package: multi-select chips from `STATE_GROUPS` (`packages/constants/src/state.ts:14`) using each group's `label` + `color`. On change → `store.setStateGroups(...)` then `store.fetchWorkload(workspaceSlug)`.                                                                                                                                                                                                          | Selecting "Started" narrows the matrix; deselecting all restores it                        |
| 1.6  | Move the over-capacity-only checkbox from `WorkloadFilters.tsx` into the toolbar as a propel `Switch` (`packages/propel/src/switch`). **No refetch** — it is a client-side row filter.                                                                                                                                                                                                                                                                               | Toggle filters rows with zero network traffic                                              |
| 1.7  | Token sweep across the whole package: `bg-white`→`bg-layer-1`, `text-gray-500/600/700`→ semantic text tokens, `border-gray-200`→`border-subtle`, plus the capacity badge, over pill (`bg-red-100`), over cell (`bg-amber-50`), meta text, and the loading / error / no-data-loaded / no-workload-data states. Confirm the exact token names against `packages/propel/src/table/core.tsx` and the propel stories before substituting — **do not invent token names**. | Every surface legible in light AND dark                                                    |
| 1.8  | Delete `src/WorkloadFilters.tsx` and its `export *` line in `src/index.ts:9`. Its store actions stay (used by `fetchWorkload`). Run a pre-delete reference grep first.                                                                                                                                                                                                                                                                                               | `grep -rn "WorkloadFilters" --include='*.ts*'` returns only the deleted file's own history |
| 1.9  | Add new i18n keys to `src/i18n.ts` (`filters.state_groups`, `filters.members`, `filters.clear`, …). Reuse existing `filters.*` keys where they already exist (`i18n.ts:56-60`).                                                                                                                                                                                                                                                                                      | No raw English literals in JSX                                                             |

**Risk in this phase:** step 1.7 is the one that can silently regress. Token names must be read from propel source, not guessed — a wrong class name compiles fine and renders unstyled.

### Phase 2 — App: render the real dropdowns into the slots

**Owner:** single agent, **after** Phase 1's prop contract lands. **Files owned:** `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx` only.

| Step | Change                                                                                                                                                                                                                                                                                                                                                                                                            |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2.1  | Import `MemberDropdown` (`@/components/dropdowns/member/dropdown`) — `multiple: true`, `value={store.selectedAssigneeIds}`, `onChange={(ids) => { store.setAssigneeIds(ids); store.fetchWorkload(slug); }}`, `buttonVariant="border-with-text"`. Member list defaults to `workspaceMemberIds` when no `projectId` is passed (`dropdown.tsx:36-40`) — correct for a workspace-level page.                          |
| 2.2  | Same shape for `ProjectDropdown` (`multiple: true` — `project/dropdown.tsx:30-32`) → `setProjectIds`.                                                                                                                                                                                                                                                                                                             |
| 2.3  | `DateRangeDropdown` with `value={{ from: new Date(store.dateFrom), to: new Date(store.dateTo) }}`, `onSelect={(range) => …}` running the package's `clampDateRange` before `setDateRange` + refetch, and `maxDate` derived from `MAX_SPAN_DAYS[store.granularity]`.                                                                                                                                               |
| 2.4  | Fix the render-phase fetch at `page.tsx:25-27`: `if (!workloadData && !isLoading && !error)` calls `fetchWorkload` **during render**, and once `error` is set no filter change can ever clear it. Move to a `useEffect` keyed on `workspaceSlug`, and have `fetchWorkload` clear `error` on entry (it already does — `store.ts:254`). Without this, the first failed request permanently freezes the new filters. |

**Note:** all four are edits to a NEW fork-owned file, not a core file — consistent with the documented precedent in `docs/FORK.md:249-251` (new `apps/web` files for workload UI). **Touch-point count is unchanged; no new core edits.**

### Phase 3 — Verify

| Check                 | Command                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| Package types         | `pnpm --filter @plane/workload-ext check:types`                                                            |
| Package build         | `pnpm --filter @plane/workload-ext build`                                                                  |
| Web types + lint      | `pnpm check`                                                                                               |
| Fork isolation        | `plane-isolation-audit` skill — must report zero core leaks                                                |
| Backend untouched     | `git diff --stat apps/api` → empty                                                                         |
| Manual: dark theme    | Load `/:slug/workload` in dark mode — no white boxes, granularity legible, dates render as a Plane popover |
| Manual: member filter | Select 2 members → matrix narrows, request carries `assignee_ids=<uuid>,<uuid>`, footer totals recompute   |
| Manual: over-capacity | Toggle → rows filter with **no** network request                                                           |

No automated frontend test suite covers this package today (`find packages/workload-ext -name '*.test.*'` → none). Phase 3 is manual + typecheck. Adding a first test file is **out of scope** and listed in §6.

---

## 4. Risk Assessment

| Risk                                                                                             | L (1-5) | I (1-5) | Score | Mitigation                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------ | ------- | ------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Wrong design-system token names — compiles clean, renders unstyled                               | 3       | 3       | 9     | Read token names from `packages/propel/src/**` source before substituting; visually verify both themes in Phase 3                                                                    |
| Users read the hidden "Unassigned" row (D4) as data loss rather than intended filtering          | 3       | 2       | 6     | Decided behavior, not a bug. Make it legible in the UI: empty member selection = all rows including Unassigned. Do **not** client-side-merge the unassigned row back in              |
| Per-selection refetch (D5) feels laggy on a slow aggregate — 4 members = 4 requests              | 3       | 2       | 6     | Decided; matches core dropdown behavior. `fetchWorkload` already sets `isLoading`, so the matrix shows its loading state per request. Revisit only if a real workspace measures slow |
| Deleting `WorkloadFilters.tsx` breaks an unseen consumer                                         | 1       | 3       | 3     | Pre-delete grep (step 1.8) — current grep already shows zero importers outside `index.ts`                                                                                            |
| `DateRangeDropdown` pulls `@headlessui`, `react-popper`, `useUserProfile` into the workload page | 2       | 1       | 2     | All already in `apps/web`'s bundle; the dropdown is used on cycles/issues pages today                                                                                                |

No risk scores ≥ 15 — no phase is gated on pre-work.

## 5. Timeline

| Phase                                        | Effort    | Notes                                                                                        |
| -------------------------------------------- | --------- | -------------------------------------------------------------------------------------------- |
| Phase 1 — package toolbar + tokens + filters | M (~3d)   | Steps 1.2/1.5/1.7 dominate; 1.7 touches every file in the package                            |
| Phase 2 — app slot wiring                    | S (~1d)   | Blocked on Phase 1's prop contract only                                                      |
| Phase 3 — verify                             | S (~0.5d) | Manual dual-theme pass is the long pole                                                      |
| **Total**                                    | **~4.5d** | Critical path: 1 → 2 → 3, strictly sequential (Phase 2 consumes Phase 1's exported contract) |

Phases 1 and 2 own disjoint file sets, but Phase 2 cannot start before the Phase 1 prop signature exists — so this is **not** a parallel-fan-out candidate. Single agent, sequential.

## 6. Explicitly out of scope

- Backend changes — none needed.
- First test file for `workload-ext` — worth doing, but not part of this change.
- The workspace page shell (`page.tsx` renders a bare `<h1>` instead of Plane's `AppHeader` / `ContentWrapper`) — a separate polish item.
- ~~Saved/persisted filter state (URL params or localStorage) — filters reset on reload.~~
  **Shipped later, out of this plan** — the reset was reported as a bug (The1Studio/plane#55) and
  the selection is now mirrored into the URL search params. See
  `packages/workload-ext/src/filterParams.ts` and the workload `page.tsx` seeding effect.
- Feature propagation (`docs/FORK.md` §Feature propagation): this ships **no new endpoint, field, or behavior** — it renders filters the API already supports. No MCP/SDK/plugin propagation required. Confirm during review.
