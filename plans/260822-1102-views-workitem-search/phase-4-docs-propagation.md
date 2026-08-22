# Phase 4 — Fork docs, isolation audit, and downstream propagation

**Parent plan:** [`plan.md`](plan.md) · **Depends on:** Phase 3

## Goal

The new `search` parameter is documented as a fork-owned surface, the new core-side edits are
recorded as declared exceptions so a future rebase treats them as expected conflict points, and the
endpoint change is propagated to the sibling repos per the standing rule in `CLAUDE.md`.

This phase is not optional bookkeeping: an undeclared core edit is what turns a routine rebase into
an abort, and an unpropagated endpoint change is how the MCP server and the SDKs drift from the API
they claim to describe.

## File ownership

- `docs/FORK.md`
- `CLAUDE.md`
- `plans/260822-1102-views-workitem-search/propagation-drafts.md` (new)

No sibling repo is edited from this repo's PR — see § "Propagation" below.

## 4.1 — `docs/FORK.md` (~1h)

### Views core-edit exception table

The § "Views multi-layout switcher (workspace Views tab)" table (around line 314) lists each fenced
core edit with a "why no seam" justification. `filter.store.ts` already has a row; extend it, and
add the new one:

| File                                                  | What to record                                                                                                                                                                                                                                                                                                                                    |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/web/core/store/issue/workspace/filter.store.ts` | **Amend the existing row.** `getAppliedFilters` now also delegates to `withGlobalViewSearch(...)` to attach the ephemeral `search` term. Why no seam: `search` is not a member of `TIssueParams` in the sealed `@plane/types`, and the term must reach param assembly without passing through `updateFilters`, which persists to the shared view. |
| `.../workspace-views/header.tsx`                      | **New row.** Mounts `WorkItemSearchInput` in `Header.RightItem`. Why no seam: the header has no plugin slot for an additional toolbar control.                                                                                                                                                                                                    |
| `apps/web/ce/store/root.store.ts`                     | **New row, or note as `ce/` seam usage** — match however the existing `workloadStore` registration is already described, so the two fork stores are documented consistently.                                                                                                                                                                      |
| `apps/web/core/hooks/store/use-views-search.ts` (NEW) | **New row.** Selector hook. Why no seam: a package hook cannot read core's `StoreContext` — same rationale as the existing `use-workload-estimate.ts` row in the SP2 workload table.                                                                                                                                                              |

Note in the section that these carry the `The1Studio fork (views-search)` fence, and that the
existing rebase rule for this table applies: on conflict re-apply the fork block and keep upstream's
changes around it; do **not** abort the rebase for a conflict confined to this set.

### Backend section

Record that `views_ext` now accepts `search` on
`GET /api/views-ext/workspaces/<slug>/issues/`, that it reuses core's
`plane.utils.issue_search.search_issues`, and that empty ≡ absent ≡ unfiltered. State explicitly
that the sibling profile endpoint does **not** accept it yet, so a reader does not assume symmetry.

### `packages/views-ext/` subsection

Add the three new modules — `search-store.ts`, `search-params.ts`, `search-input.tsx` — and the
package's newly-widened dependency set (react, mobx, propel), mirroring how `workload-ext` is
described.

## 4.2 — `CLAUDE.md` "Custom features" entry (~15m)

Extend the existing `views_ext/` bullet. It currently ends at the multi-layout switcher; append the
search surface in the same voice — one line, factual, naming the parameter and its match rule, and
stating that an absent or empty `search` returns everything.

Be explicit that the term is ephemeral and never written to the saved view, since that is the
non-obvious property an API consumer or a future maintainer would otherwise assume wrong.

## 4.3 — Isolation audit (~30m)

```bash
node .claude/scripts/plane-classify-path.cjs $(git diff --name-only origin/company-main...HEAD)
```

Every changed path must classify as `custom-app`, `custom-package`, a declared touch-point, or a
row now present in the `FORK.md` exception table. A path classifying as bare `core` with no matching
row is a leak — relocate the edit or add the row; do not suppress the finding.

Then run the fork's own skills as the second opinion: `plane-isolation-audit`, and
`plane-fork-doctor` for overall fork health.

## 4.4 — Propagation (~1h)

`CLAUDE.md` carries a standing rule: every new endpoint, field or behavior must be propagated
downstream before the feature is considered done. A new query parameter on a fork-owned endpoint is
squarely in scope.

Draft the propagation items into `propagation-drafts.md` in this plan directory (the switcher plan
did the same — see `plans/260817-1616-views-layout-switcher/propagation-drafts.md` for the format),
then file them as issues/PRs **in the sibling repos**:

| Repo                                              | What                                                                                                                                                                                          |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plane-mcp-server`                                | Whichever tool wraps the views-ext workspace issues endpoint gains a `search` argument. If no such tool exists yet, that absence is itself the finding — record it rather than inventing one. |
| `plane-node-sdk`                                  | `search` on the corresponding binding                                                                                                                                                         |
| `plane-python-sdk`                                | Same                                                                                                                                                                                          |
| `plane-claude-plugin` / `docs` / `developer-docs` | Update only where the endpoint's parameters are actually documented                                                                                                                           |

Use the `plane-propagate` skill; the sibling matrix and classification rule live in
`.claude/skills/plane-propagate/references/sibling-repos.md`.

**Boundary — do not cross it.** Open the issue or PR in the sibling repo and report the URL. Never
edit a sibling repo from this repo's PR, and do not babysit, merge or resolve conflicts on a
sibling PR from this session (`.claude/rules/plane-fork-discipline.md`;
`rules/kit-pr-workflow-boundary.md`).

## 4.5 — Record the adjacent defect (~15m)

Before closing, file the `header.tsx:117-120` `currentLayoutFilters` defect (plan.md § "Adjacent
defect observed") as its own tracked item, so it does not die in this PR's description. It is a
one-line fix — swap to the already-exported `GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS` — but it wants its
own review, and it is currently making the Display dropdown render against `undefined` on three of
the five layouts.

## Success criteria

- [ ] `docs/FORK.md` lists every fenced `views-search` core edit with a "why no seam" justification
- [ ] `CLAUDE.md` `views_ext/` bullet names the `search` parameter, its match rule, and its ephemerality
- [ ] `plane-classify-path.cjs` returns no undeclared `core` path across the branch
- [ ] `plane-isolation-audit` and `plane-fork-doctor` clean
- [ ] Sibling-repo issues/PRs opened, URLs reported, nothing in those repos edited from here
- [ ] The `currentLayoutFilters` defect is tracked somewhere durable
