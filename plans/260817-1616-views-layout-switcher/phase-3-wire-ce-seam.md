# Phase 3 — Wire the `ce/` seam · **first shippable increment**

**Goal:** Connect Phase 2's package to the app. At the end of this phase the Views tab shows a
working 3-button switcher (List · Board · Spreadsheet) with server-side grouping.

**Effort:** S (~1d) · **Depends on:** Phases 1 and 2 · **Blocks:** 4, 5

---

## Why this phase is one day

Upstream already built the seam and wired it into the header and the layout dispatcher. Both
integration points call into `apps/web/ce/components/views/helper.tsx`, whose two exports return
`<></>`. Filling them is the entire UI integration:

- `workspace-views/header.tsx:155` already renders `<GlobalViewLayoutSelection …>`
- `core/components/views/helper.tsx:55` already falls through to `<WorkspaceAdditionalLayouts {...props} />`

**Neither file needs an edit.** Verify both still look this way before starting — if upstream has
moved them since this plan was written, re-home rather than force it (`docs/FORK.md` § Conflict
recovery).

## Edit 1 — the `ce/` stubs (sanctioned exception)

`apps/web/ce/components/views/helper.tsx`

Replace the two `<></>` bodies with delegations to `@plane/views-ext`:

- `GlobalViewLayoutSelection` → Phase 2's switcher
- `WorkspaceAdditionalLayouts` → a `switch` on `activeLayout` returning Phase 2's List / Board
  roots; `default: return <></>` so an unhandled layout degrades to blank rather than crashing.
  Phases 4 and 5 add cases here.

Leave `AdditionalHeaderItems` untouched — unrelated to this feature.

**Keep the bodies to delegations only.** Every line of logic belongs in the package. This file is
the permanent rebase-conflict surface; the smaller it is, the cheaper every future rebase.
Fence with `// The1Studio fork (views-layouts)`.

`docs/FORK.md` already sanctions this class of edit: it lists
`apps/web/ce/components/issues/issue-layouts/additional-properties.tsx` as "the `ce/` stub seam
(`WorkItemLayoutAdditionalProperties`) is the intended injection point". Same pattern, different
stub. Phase 6 adds this file to that table.

## Edit 2 — layout-aware query params (**resolves B1**)

`apps/web/core/store/issue/workspace/filter.store.ts`, in `getAppliedFilters` (~line 101):

```ts
// currently:
const filteredParams = handleIssueQueryParamsByLayout(EIssueLayoutTypes.SPREADSHEET, "my_issues");
```

Delegate to Phase 2's param builder, passing `userFilters?.displayFilters?.layout`. One line
changed plus one import.

Without this the switcher visibly works and the data silently does not — the request keeps
sending the spreadsheet param set, `group_by` never reaches the server, and Board renders a
single column. That failure looks like a backend bug, so fix it here and confirm it on the wire
(see success criteria — inspect the request, do not infer from the rendering).

## Edit 3 — admit `GLOBAL` to the store-type unions

Add `| EIssuesStoreType.GLOBAL` to:

- `apps/web/core/components/issues/issue-layouts/list/base-list-root.tsx:30` — `ListStoreType`
- `apps/web/core/components/issues/issue-layouts/kanban/base-kanban-root.tsx:36` — `KanbanStoreType`

One line each, fenced. Both unions already contain `EIssuesStoreType.PROFILE`, which is likewise
workspace-level and cross-project — this is admitting a sibling, not widening the contract.

## Edit 4 — point the store at the new endpoint

`apps/web/core/services/workspace.service.ts` → `getViewIssues` (~line 272) currently targets
`/api/workspaces/<slug>/issues/`, which has no grouping.

Route to Phase 1's `/api/views-ext/workspaces/<slug>/issues/`. Prefer routing **all** global-view
requests there — Phase 1's ungrouped response is shape-identical to the core endpoint, so a single
target avoids a params-dependent branch that would need re-verifying on every future param
addition. Confirm that shape-identity against a live response before committing to it; if it
diverges, branch on `params.group_by` instead and say so in a comment.

## Also owned by Phase 3 — suppress the dead quick-add button (cross-cutting)

Found during Phase 5 pre-audit, affects **every** new layout. `WorkspaceIssues.viewFlags.enableIssueCreation`
is `true` (`store/issue/workspace/issue.store.ts:60`), so the quick-add gate passes — but
`useWorkspaceIssueActions` (`use-issues-actions.tsx:722-733`) returns no `quickAddIssue` key at
all. The button renders wired to `undefined`: no crash, no type error, just a control that
silently does nothing. That is why it survived upstream.

Set `enableIssueCreation: false` on `WorkspaceIssues.viewFlags`. One line, fixes List, Board,
Calendar and Timeline at once. A workspace-wide view has no unambiguous target project, so no
button is the honest answer. Full detail: [`phase-5-timeline.md`](phase-5-timeline.md) § Quick-add.

## Core-edit budget · **revised 2026-08-17**

Phase 2's roots turned out to be core files, not package files (the `@/` alias does not resolve
from a workspace package — see [`phase-2-frontend-package.md`](phase-2-frontend-package.md) § D3).
Two are NEW files, which carry near-zero rebase-conflict surface. Revised total — 5 edited + 2 new:

| File | Lines | Class |
|---|---|---|
| `.../issue-layouts/list/roots/workspace-root.tsx` | NEW | New core file (Phase 2 authored) |
| `.../issue-layouts/kanban/roots/workspace-root.tsx` | NEW | New core file (Phase 2 authored) |
| `apps/web/core/store/issue/workspace/issue.store.ts` | 1 | Documented exception — quick-add suppression above |
| `apps/web/core/hooks/use-group-dragndrop.ts` | 1 | **Found during verification, not planned** — see below |

### `use-group-dragndrop.ts` — the union widening propagates

Adding `GLOBAL` to `ListStoreType` / `KanbanStoreType` produced two real `tsc` errors: both roots
pass `storeType` into `useGroupIssuesDragNDrop`, whose own `DNDStoreType` union also excluded
`GLOBAL`. Not discoverable by reading the phase file — only the typecheck surfaced it.

Admitting `GLOBAL` there is safe, and was checked rather than assumed: the hook reads only
`workspaceSlug` from the route (present on `/workspace-views/`) and takes `projectId` **per issue**
as a function argument; its cycle/module branches are unreachable for global views because D3
excludes both from the group-by set. `DNDStoreType` already contained `PROFILE`, the same
cross-project workspace-level store.

**Final tally: 7 core files, not the 5 originally budgeted** — 5 edited as planned, plus
`issue.store.ts` (quick-add) and `use-group-dragndrop.ts` (above). Phase 6 documents all seven.

plus the originally-budgeted edits:

| File                                                                        | Lines      | Class                                 |
| --------------------------------------------------------------------------- | ---------- | ------------------------------------- |
| `apps/web/ce/components/views/helper.tsx`                                   | ~6         | Sanctioned `ce/` stub seam            |
| `apps/web/core/store/issue/workspace/filter.store.ts`                       | 1 + import | Documented exception (no seam exists) |
| `apps/web/core/components/issues/issue-layouts/list/base-list-root.tsx`     | 1          | Documented exception                  |
| `apps/web/core/components/issues/issue-layouts/kanban/base-kanban-root.tsx` | 1          | Documented exception                  |
| `apps/web/core/services/workspace.service.ts`                               | ~2         | Documented exception                  |

`plane-isolation-audit` **will flag all five** — that is expected and correct. They are accepted
under the same "no upstream seam" clause as the SP2 workload edits. Phase 6 records them in
`docs/FORK.md`; until it does, the audit output is a true positive, not noise.

## Success criteria

- [ ] Views tab renders 3 switcher buttons: List, Board, Spreadsheet
- [ ] Switching layout persists across a page reload (display filters already persist — verify, do not assume)
- [ ] Board grouped by Priority renders one column per priority — **confirmed in the network tab**: the request carries `group_by=priority` and the response is a keyed dict
- [ ] Board grouped by Project renders one column per project
- [ ] List with group-by None renders a single "All work items" group
- [ ] Infinite scroll / next-page loads more within a group
- [ ] Peek overview still opens from every layout
- [ ] Spreadsheet is byte-for-byte unchanged from today — this is the regression guard
- [ ] Every core edit carries the `The1Studio fork (views-layouts)` fence
- [ ] `pnpm check` clean
- [ ] `plane-isolation-audit`: only the 5 files above flagged, no others

## Risks

| Risk                                                                  | L   | I   | Score | Mitigation                                                                               |
| --------------------------------------------------------------------- | --- | --- | ----- | ---------------------------------------------------------------------------------------- |
| Switcher renders but requests stay ungrouped (Edit 2 missed or wrong) | 3   | 4   | 12    | Success criteria require reading the network request, not the rendered board             |
| Spreadsheet regresses while routing to the new endpoint               | 2   | 4   | 8     | Explicit unchanged-Spreadsheet criterion; verify shape-identity on a live response first |
| Core-edit set creeps past 5 files                                     | 2   | 3   | 6     | Anything beyond the table means logic leaked out of the package — move it back           |
