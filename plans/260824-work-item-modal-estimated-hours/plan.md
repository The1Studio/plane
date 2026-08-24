# "Estimated hours" input in the Add-work-item modal

**Created:** 2026-08-24
**Branch:** `feat/work-item-modal-estimated-hours`
**Plane:** [PLANE-127](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/023fe786-f94c-4d2c-91b6-dc75034a7853) — parent, Infrastructure › Plane · sub-tasks PLANE-128 (P1, 2h) · PLANE-129 (P2, 3h) · PLANE-130 (P3, 2.5h) · PLANE-131 (P4, 1h)
**Scope:** frontend only — one new `packages/workload-ext` module pair, one new core component file,
three fenced core edits. **No backend change, no migration, no new endpoint, no sibling-repo propagation.**

## Problem

`WorkloadEstimate` hours can be set from four places today — the spreadsheet grid cell, the peek
panel, the issue-detail sidebar, and the API. All four require the work item to **already exist**.
Creating a work item and giving it an estimate is therefore always two steps: create, then reopen
the item somewhere else and type the hours. The Add-work-item modal is where every other property
(state, priority, assignees, labels, dates, story points, cycle, module) is set at creation time,
and hours are conspicuously the one property missing from it.

## Prior art — searched, and the gap is real

| Question                                     | Answer                                                                                                                  | Scope searched                                                                                                                                           |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Does any create-time hours input exist?      | **No.** Zero matches for an hours field in any create path.                                                             | `apps/web/core/components/issues/issue-modal/`, `apps/web/core/components/issues/issue-layouts/quick-add/`, `apps/web/ce/components/issues/issue-modal/` |
| Is there a shared commit lifecycle to reuse? | **Yes** — `useWorkloadEstimateEditor` (800 ms debounce, Enter flush, blur flush, never auto-commits empty).             | `apps/web/core/hooks/store/use-workload-estimate-editor.ts`                                                                                              |
| Is there a store write path to reuse?        | **Yes** — `WorkloadStore.updateEstimate(slug, projectId, issueId, hours)` → `PUT /api/workload/.../workload-estimate/`. | `packages/workload-ext/src/store.ts:426`, `service.ts:59`                                                                                                |
| Is there a backend gap?                      | **No.** `PUT` already creates-or-updates; `WorkloadEstimateSerializer` already validates and quantizes.                 | `apps/api/plane/workload/{views,serializers,api_urls}.py`                                                                                                |
| Does the MCP/SDK layer need a new tool?      | **No.** `set_issue_workload_estimate` already exists and is unchanged by this work.                                     | `plane-mcp-server` tool list surfaced in this session                                                                                                    |
| Can a draft carry an estimate?               | **No.** Drafts live in `draft_issues`; `WorkloadEstimate.issue` FKs `db.Issue`.                                         | `apps/api/plane/db/models/draft.py:16`, `apps/api/plane/workload/models.py:36`                                                                           |

Everything this feature needs on the write side already ships. The work is entirely
_"hold a number while the work item does not exist yet, then write it the moment it does."_

## Decisions (resolved — do not revisit at cook time)

| #   | Decision                                                                                                                                                       | Consequence                                                                                                                                                                                                                                                                                                  |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | **Update mode live-commits**, reusing `useWorkloadEstimateEditor` verbatim.                                                                                    | The PUT fires on debounce/Enter/blur, independently of the modal's Save button — identical to the spreadsheet cell, peek panel and sidebar. **Discard does not revert the estimate**, and that is intended: it is how every other hours input in the fork already behaves.                                   |
| D2  | **Create mode holds a draft value in React state** and writes it once, after the work item exists.                                                             | No PUT is possible before the item has an id. The held value is a plain string in a fork-owned context, never part of `TIssue` or the react-hook-form schema — `TIssue` is a `@plane/types` shape the fork must not edit.                                                                                    |
| D3  | **Placement: the bottom properties row, immediately after the `target_date` dropdown**, before the cycle block.                                                | Matches the sidebar, which puts "Estimated hours" next to the Start/Due date rows. One fenced insertion in `default-properties.tsx` between the `target_date` `Controller` and the cycle `Controller`.                                                                                                       |
| D4  | **Scope is the create + update modal only.**                                                                                                                   | `CreateUpdateIssueModalBase` / `IssueFormRoot` — every place the popup opens (project, cycle, module, workspace, sub-item, "New work item" command). The inline quick-add row stays title-only.                                                                                                              |
| D5  | **The field is hidden when `isDraft` is true.**                                                                                                                | A draft has no `db.Issue` row to FK. No backend change, no draft-side storage.                                                                                                                                                                                                                               |
| D6  | **Saving a create-modal item _as a draft_ with hours entered drops the hours, and says so.**                                                                   | The "save as draft" path (`handleCreateIssue(payload, true)` from `handleClose`, and `DraftIssueLayout`'s discard-confirm) skips the PUT and raises one warning toast. Silently discarding a typed number is the failure mode this avoids.                                                                   |
| D7  | **The estimate PUT runs _before_ `handleCreateSubWorkItem`.**                                                                                                  | That helper can turn the freshly created item into a parent, and the backend rejects an estimate on a parent with `PARENT_HAS_CHILDREN`. Ordering is the whole guard. (It is a no-op in the CE provider today — the ordering is defence against the EE path and against a future change, and costs nothing.) |
| D8  | **A failed estimate PUT never fails the create.**                                                                                                              | The work item is already created and the success toast has meaning. A failure raises its own error toast naming the estimate specifically, and leaves the item in place.                                                                                                                                     |
| D9  | **Input parsing is extracted to one shared helper** in `packages/workload-ext`, used by both the new create path and the existing `useWorkloadEstimateEditor`. | The trim / empty / `Number` / finite / `>= 0` logic currently lives only inside the editor hook's `commit`. A second copy in the create path is the duplicate `code-conventions.md` § "No Duplicated Logic" forbids at the second occurrence.                                                                |
| D10 | **In update mode, a parent renders read-only**, keyed on `rollup !== null`, exactly as the spreadsheet cell does.                                              | Reuses `useWorkloadEstimate(issueId).rollup` and the same `formatRollupHours` / `formatRollupTooltip` display.                                                                                                                                                                                               |
| D11 | **The held value survives a project change in create mode; it resets after a successful create.**                                                              | Hours are project-independent, so the `reset()` on project switch must not clear them. "Create more" must clear them, or the next item silently inherits the previous one's estimate.                                                                                                                        |

## Architecture

```
packages/workload-ext/                     ← fork-owned, no core coupling
  src/estimateInput.ts        (NEW)  parseEstimateHoursInput(raw) → number | null
  src/PendingEstimate.tsx     (NEW)  PendingEstimateProvider + usePendingEstimate

apps/web/core/components/issues/issue-modal/
  components/estimated-hours-input.tsx (NEW, fork-owned)
        ├── CreateModeInput  → usePendingEstimate()          (no network)
        └── UpdateModeInput  → useWorkloadEstimateEditor()   (live PUT)
  components/default-properties.tsx    (FENCED EDIT)  renders it after target_date
  components/index.ts                  (FENCED EDIT)  one export line
  base.tsx                             (FENCED EDIT)  wraps the provider, writes on create
```

The split into two sibling components is not cosmetic: `useWorkloadEstimateEditor` needs an
`issueId`, which does not exist in create mode, and a hook cannot be called conditionally. Each
component calls its own hook unconditionally; the parent picks which to render on `!!id`.

`PendingEstimate` lives in the package rather than in core because it holds nothing but local React
state — unlike `useWorkloadEstimate` / `useWorkloadEstimateEditor`, which are in core precisely
because they must call `useWorkload()`, and a context-agnostic package hook cannot.

## Phases

| Phase | File                     | Deliverable                                                                                | Effort |
| ----- | ------------------------ | ------------------------------------------------------------------------------------------ | ------ |
| 1     | [phase-1.md](phase-1.md) | `packages/workload-ext` — parse helper, pending-estimate context, i18n strings, unit tests | 2h     |
| 2     | [phase-2.md](phase-2.md) | The input component + its placement in the properties row                                  | 3h     |
| 3     | [phase-3.md](phase-3.md) | `base.tsx` create-path wiring: provider, post-create write, reset, draft warning           | 2.5h   |
| 4     | [phase-4.md](phase-4.md) | `docs/FORK.md` exception rows, `CLAUDE.md` feature entry, propagation assessment           | 1h     |

Phases are strictly sequential — 2 imports 1, 3 imports 1 and consumes 2's placement, 4 documents
all three. Single-agent execution; no fan-out, no worktrees.

**Total: 8.5h.** Critical path is the whole chain.

## Risk Assessment

| Risk                                                                                                  | L   | I   | Score | Mitigation                                                                                                                                                                                                                                       |
| ----------------------------------------------------------------------------------------------------- | --- | --- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Estimate PUT lands after the item becomes a parent → `PARENT_HAS_CHILDREN` 400 on a brand-new item    | 2   | 4   | 8     | D7 — the PUT runs before `handleCreateSubWorkItem`, and D8 keeps the failure non-fatal with its own toast                                                                                                                                        |
| "Create more" silently carries the previous item's hours into the next one                            | 3   | 3   | 9     | D11 — explicit reset in the same block that resets the form; called out as a manual verification step in phase 3                                                                                                                                 |
| Refactoring `useWorkloadEstimateEditor` onto the shared parse helper changes existing commit behavior | 2   | 4   | 8     | Phase 1 extracts the helper as a byte-equivalent transcription of the existing branch order, with unit tests written against the CURRENT behavior first; phase 1 lands the helper and its tests before the hook is touched                       |
| Modal unmounts mid-debounce in update mode, dropping an edit                                          | 2   | 3   | 6     | Already solved upstream — the hook flushes rather than cancels on unmount. Verify by typing and immediately pressing Discard                                                                                                                     |
| Store not warm in update mode → field shows empty for an item that has hours                          | 3   | 3   | 9     | Update variant mirrors the sidebar's single-fetch effect (`workloadStore.fetchEstimate`, ref-guarded), which populates estimate **and** rollup in one call                                                                                       |
| Frontend vitest is not run by CI                                                                      | 4   | 2   | 8     | Known gap, pre-existing (`cascade-ext` tests are also ungated — `company-main-ci.yml` runs `pnpm check` and the web build, never `turbo run test`). Phase 1 states the local command; **out of scope to fix here**, flagged for a separate issue |
| Rebase conflict on the three fenced core files                                                        | 3   | 2   | 6     | Each edit is a few lines inside a `The1Studio fork (SP2 workload)` fence; `docs/FORK.md` already declares this file set an expected conflict point with re-apply-don't-abort handling                                                            |

No risk scores ≥ 15.

## Verification

There is no frontend test runner in CI, so the gate is:

```bash
pnpm check                                    # lint + types + format, all workspaces
pnpm turbo run build --filter=web             # the SSR prerender CI also runs
pnpm --filter @plane/workload-ext test        # phase 1's unit tests (local only)
```

Manual, in a running dev server — each is a decision above made observable:

1. Create a work item with `4.5` in the field → the item appears with 4.5h in the spreadsheet's Estimated-hours column. (D2)
2. Create with the field left empty → no estimate row is written; the column reads blank, not `0`. (D2)
3. Toggle "Create more", create two items with different hours → the second does **not** inherit the first's. (D11)
4. Open an existing item in the modal → the field is pre-filled; typing a new value and waiting 800 ms writes it without pressing Save. (D1)
5. Open a **parent** item in the modal → the field is read-only and shows the Σ rollup. (D10)
6. Open the modal in draft mode → no field at all. (D5)
7. Type hours in a create modal, then Discard → "save as draft" path warns that hours are not saved on drafts. (D6)

## Out of scope

- The inline quick-add row in list / kanban / spreadsheet / calendar (D4).
- Any change to `useWorkloadEstimateEditor`'s commit _timing_ — only its parse step is extracted.
- Wiring frontend vitest into `company-main-ci.yml` — a real pre-existing gap, but a separate change.

## Downstream propagation

Per `CLAUDE.md` § "STANDING RULE", propagation was assessed and is **nil**: this adds no endpoint,
no field, and no API behavior. `plane-mcp-server`'s `set_issue_workload_estimate`, the SDK bindings,
and the docs all describe the same unchanged `PUT`. Phase 4 records that assessment rather than
opening empty sibling issues.
