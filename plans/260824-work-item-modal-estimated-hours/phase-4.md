# Phase 4 — Documentation and propagation assessment

**Plan:** [plan.md](plan.md) · **Effort:** 1h · **Depends on:** phases [1](phase-1.md)–[3](phase-3.md) · **Blocks:** nothing

## Goal

Record the three new core-edit exceptions where the rebase workflow will look for them, extend the
fork-owned feature entry, and close out the standing propagation rule honestly.

## Ownership

```
docs/FORK.md    (append rows to the existing "Frontend core-edit exceptions" table)
CLAUDE.md       (extend the `workload/` bullet under "Custom features (fork-owned)")
```

## Steps

### 1. `docs/FORK.md` § "Frontend core-edit exceptions"

Append four rows to the existing table (same three-column shape: File · What · Why no seam). The
table is the input to the rebase procedure — a fenced edit missing from it is an edit nobody
re-applies after a conflict.

| File                                                         | What                                                                                                                  | Why no seam                                                                                                                             |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `.../issue-modal/components/estimated-hours-input.tsx` (NEW) | "Estimated hours" control for the Add-work-item modal — create-mode draft + update-mode live editor, parent read-only | New file; must call core's `useWorkloadEstimateEditor` / `useWorkload`, which a `packages/` component cannot                            |
| `.../issue-modal/components/default-properties.tsx`          | Renders the control after the `target_date` dropdown                                                                  | The properties row is a hard-coded list of `Controller`s; no registry or slot to inject a property into                                 |
| `.../issue-modal/components/index.ts`                        | One export line                                                                                                       | Barrel file; the modal's components resolve through it                                                                                  |
| `.../issue-modal/base.tsx`                                   | Wraps `PendingEstimateProvider`; PUTs the held estimate after create, before `handleCreateSubWorkItem`                | The estimate lives in a separate table and cannot ride the issue POST; the write has to happen where the created item's id first exists |

Leave the existing "Rebase handling" paragraph as is — it already covers this file set by naming the
`The1Studio fork (SP2 workload)` fence, and every edit above carries that fence.

### 2. `CLAUDE.md` § "Custom features (fork-owned)"

Extend the existing `workload/` bullet — do **not** add a new bullet; this is the same feature. Add,
in the entry's own voice, the facts a future session would otherwise have to re-derive:

- The Add-work-item modal now carries the same "Estimated hours" input, placed after the Due-date
  dropdown.
- **In create mode it does not save as you type** — the value is held in React state and written
  with a single PUT after the work item is created, because there is no id to PUT against before
  that. In update mode it live-commits on the same 800 ms / Enter / blur lifecycle as every other
  hours input, so **Discard does not revert an estimate edit**.
- An untouched field writes **nothing** — no `0` row.
- The field is **absent in draft mode**, and saving a create-modal item as a draft warns that the
  hours are dropped: `WorkloadEstimate.issue` FKs `db.Issue`, and drafts live in `draft_issues`.
- The create-mode PUT runs **before** `handleCreateSubWorkItem` on purpose — a new parent cannot
  take an estimate (`PARENT_HAS_CHILDREN`).
- Opening a **parent** in the modal shows the read-only Σ rollup, matching the spreadsheet cell.
- `parseEstimateHoursInput` in `packages/workload-ext` is the SSOT for what an hours input accepts;
  it deliberately does not enforce `MAX_HOURS`, which the server owns.
- The inline quick-add row is **not** in scope and stays title-only.

### 3. Propagation assessment (the standing rule)

`CLAUDE.md` § "STANDING RULE" requires every new endpoint, field, or behavior to reach
`plane-mcp-server` → the SDKs → `plane-claude-plugin` / docs. Assess and record, rather than opening
empty issues:

| Sibling                                           | Change needed | Why                                                                                                       |
| ------------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------- |
| `plane-mcp-server`                                | **None**      | `set_issue_workload_estimate` already wraps the same unchanged `PUT`. This phase adds no parameter to it. |
| `plane-node-sdk` / `plane-python-sdk`             | **None**      | No endpoint, no request field, no response field changed.                                                 |
| `plane-claude-plugin` / `docs` / `developer-docs` | **None**      | Nothing user-facing about the API changed; the change is a web-UI affordance.                             |

State this conclusion **in the PR description**, naming the endpoint that already exists, so a
reviewer can see propagation was assessed rather than forgotten. Verify before writing it: confirm
`set_issue_workload_estimate` is still present in the installed MCP tool surface and that its
signature has not drifted. If it has, that is a propagation item after all — open it in the sibling
repo, never from this repo's PR (`.claude/rules/plane-fork-discipline.md`).

### 4. Known gap to file separately

Frontend vitest does not run in CI: `company-main-ci.yml` runs `pnpm check` and
`pnpm turbo run build --filter=web`, never `turbo run test`. Phase 1's tests — and the existing
`packages/cascade-ext` tests — are therefore ungated. Open a **separate** issue on
`The1Studio/plane` for wiring `turbo run test` into `frontend-check`. Do not fold it into this PR;
it changes the CI contract for the whole repo and deserves its own review.

## Success criteria

- `docs/FORK.md` lists all four paths; `grep -c "issue-modal" docs/FORK.md` ≥ 4.
- Every path in that table exists on disk and carries a `The1Studio fork (SP2 workload)` fence:
  verify by grepping each listed file for the fence string, not by trusting the table.
- `CLAUDE.md`'s `workload/` bullet states the create-vs-update save difference explicitly — a
  future reader must not have to discover from code that Discard does not revert an estimate.
- The PR description carries the propagation table above.
- A separate CI issue exists, with its URL noted in the PR description.
