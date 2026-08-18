# Phase 6 — Fork documentation and propagation

**Goal:** Record every core edit this feature introduced, so the next monthly rebase knows what to
re-apply and `plane-isolation-audit` stops reporting true-but-expected positives.

**Effort:** S (~1d) · **Depends on:** all code phases landed

---

## Why this is a phase and not a chore

`docs/FORK.md` is the SSOT for what may carry fork edits. Until this phase lands, five to seven
core files carry fenced edits that the audit correctly flags as violations and that the rebase
runbook says to **abort** on:

> "If a conflict appears OUTSIDE touch-points 1-7: this means custom code leaked into a core file.
> Run `git rebase --abort` …"

An undocumented edit therefore does not just lack a doc entry — it actively instructs the next
rebase operator to abort and relocate work that was deliberate. Skipping this phase converts a
designed exception into a landmine.

## 1. `docs/FORK.md` § Frontend core-edit exceptions

Append one row per core file, matching the existing SP2 workload table's columns
(File · What · Why no seam). Give this feature its own fence marker,
`The1Studio fork (views-layouts)`, so it is distinguishable from the workload block.

| File                                                  | What                                                                            | Why no seam                                                                                        |
| ----------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `apps/web/ce/components/views/helper.tsx`             | `GlobalViewLayoutSelection` + `WorkspaceAdditionalLayouts` → `@plane/views-ext` | The `ce/` stub seam — the intended injection point, same class as `additional-properties.tsx`      |
| `apps/web/core/store/issue/workspace/filter.store.ts` | Layout-aware query params (was hardcoded to Spreadsheet)                        | No seam; every sibling store already does this — upstream simply never made the global one dynamic |
| `apps/web/core/services/workspace.service.ts`         | Route global-view issue fetches to `/api/views-ext/…`                           | No service-layer override point                                                                    |
| `.../issue-layouts/list/base-list-root.tsx`           | `+ EIssuesStoreType.GLOBAL` in `ListStoreType`                                  | Sealed union type; admitting a sibling of the existing `PROFILE` member                            |
| `.../issue-layouts/kanban/base-kanban-root.tsx`       | `+ EIssuesStoreType.GLOBAL` in `KanbanStoreType`                                | Same                                                                                               |
| `.../issue-layouts/calendar/base-calendar-root.tsx`   | `+ EIssuesStoreType.GLOBAL` in `CalendarStoreType`                              | Same (Phase 4) — omit if Phase 4 was deferred                                                      |
| `.../issue-layouts/gantt/base-gantt-root.tsx`         | `+ GLOBAL` in `GanttStoreType`; per-item date-update fallback (D5/B3)           | Same, plus `updateIssueDates` is project-scoped by API shape (Phase 5) — omit if deferred          |

Add the standard rebase-handling note used by the workload block: **these files are expected
conflict points**; on conflict re-apply the fenced hunk and keep upstream's changes around it —
do **not** abort.

Also record, in the same section or an adjacent note:

- `packages/views-ext/` is fork-owned despite the `@plane/` npm scope — the same clarification
  `docs/FORK.md` already carries for `@plane/workload-ext`, so the isolation audit does not
  false-flag it as a sealed-package edit.
- Why `packages/views-ext` carries its own layout-options table (blocker B2): `@plane/constants`'
  `my_issues.layoutOptions` lacks kanban / calendar / gantt entries and is sealed. Without this
  note the table reads as a gratuitous duplicate and someone will "consolidate" it.

## 2. Backend app inventory

`docs/FORK.md` § Isolation convention lists the current fork apps
(`ai_ext`, `clickup_migrate`, `workload`, `github_ext`, `project_ext`). Add `views_ext`.

## 3. Convention mirror — verify, do not re-edit

`.claude/skills/_shared/references/fork-convention.md` mirrors `docs/FORK.md`, and
`plane-fork-doctor` **fails on drift** between them. Phase 1 already added `views_ext` to the
`forkApps` JSON array there; this phase confirms the prose fork-app list in the same file matches
step 2, and that no other section drifted.

Run `plane-fork-doctor` — a clean run is the check. Do not hand-diff.

## 4. Propagate the new endpoint

`.claude/rules/plane-fork-discipline.md` § Feature propagation makes this mandatory, not optional:

> Every new endpoint, field, or behavior must be propagated before the feature is considered done.

`GET /api/views-ext/workspaces/<slug>/issues/` is a new public endpoint. Open tracking issues in
the sibling repos — **do not edit them from this repo's PR**:

- `plane-mcp-server` — an MCP tool for grouped workspace-view queries
- `plane-node-sdk` / `plane-python-sdk` — bindings for the endpoint
- `CLAUDE.md` § "Custom features" — one entry for the Views multi-layout feature

Use the `plane-propagate` skill; it knows the repo set and the issue format.

## Success criteria

- [x] `docs/FORK.md` frontend exception table has one row per core file actually edited — cross-checked against the `The1Studio fork (views-layouts)` fence grep (no Bash/`git diff` available to this agent; see report) — 7 edited + 2 new core files documented; Calendar/Timeline rows left as placeholders (Phases 4/5 in progress concurrently)
- [x] Rebase-handling note present for the `views-layouts` fence
- [x] `packages/views-ext` fork-ownership clarification recorded
- [x] B2 rationale recorded, so the fork layout table is not later "consolidated" away
- [x] `views_ext` in the `docs/FORK.md` fork-app list
- [ ] `plane-fork-doctor`: clean (no SSOT/mirror drift) — NOT RUN, this agent has no Bash tool; needs a teammate/lead to execute
- [ ] `plane-isolation-audit`: every flagged file is now a documented exception; zero undocumented — NOT RUN for the same reason; classify-path output requested from a teammate, pending
- [ ] Propagation issues opened in `plane-mcp-server`, `plane-node-sdk`, `plane-python-sdk` — DRAFTED ONLY per instruction, not filed (`propagation-drafts.md`); needs explicit user approval
- [x] `CLAUDE.md` § Custom features entry added (note: `CLAUDE.md` did not exist in this repo prior to this session — created fresh)

## Risks

| Risk                                                                              | L   | I   | Score | Mitigation                                                                  |
| --------------------------------------------------------------------------------- | --- | --- | ----- | --------------------------------------------------------------------------- |
| Doc table drifts from the real edit set (phases deferred, or extra files touched) | 3   | 3   | 9     | Cross-check against `git diff --name-only`, never against this file's table |
| Mirror drift fails `plane-fork-doctor` after merge                                | 2   | 3   | 6     | Run the doctor as the check, not a manual read                              |
| Propagation deferred and forgotten                                                | 3   | 2   | 6     | Issues opened in this phase; the feature is not done until they exist       |
