# Phase 6 — Docs, FORK.md, sibling-repo propagation

**Goal:** record the fork surface this feature adds (settings, week-start propagation, and the timeline UI), and propagate the new/changed API to the
downstream sibling repos. Depends on Phases 3 and 5. This phase is what makes the feature _done_
under the standing rule in `CLAUDE.md`.

Parent plan: [`plan.md`](plan.md).

## Ownership

`docs/FORK.md`, `plans/**`, and a new operator migration note under `docs/`.

**`CLAUDE.md` is NOT in scope and cannot be** — it is gitignored (`.gitignore:104`) and untracked, so
it can never appear in a commit or a PR diff. Update the local copy on disk if you want it current,
but do not expect or look for a diff. **No sibling repo is edited from this repo's PR** —
propagation is tracked via issues/PRs opened in those repos (`.claude/rules/plane-fork-discipline.md`).

## `docs/FORK.md`

1. Update the `workload/` bullet in the fork-owned apps list: per-issue estimates plus
   **workspace-wide work settings** (max weekly hours, workdays, week start); note that
   `WorkloadCapacity` was removed and the grain is now workspace-only.
2. Add every Phase 5 file — and any Phase 8 gantt edit, if the composition attempt proved insufficient — to the **"Frontend core-edit exceptions"** table with its _why-no-seam_
   reason. The nav-entry edit from Phase 4 (`item-categories.tsx`) goes in the same table — its
   reason is identical to the existing `sidebar-menu-items.tsx` row (nav arrays live in the sealed
   `@plane/constants`).
3. Record the `apps/space` carve-out from Phase 5 explicitly, so a later audit does not read it as
   a missed site.
4. Note the deliberate divergence: `DEFAULT_WEEK_START_DAY = Monday` (workspace) vs core's Sunday
   per-user default, and why (preserves existing ISO-week bucketing).

## `CLAUDE.md`

Extend the `workload/` line under "Custom features (fork-owned)" to name the workspace work
settings and the settings page route.

## Changelog / migration note (ships before deploy)

The plan's highest-scoring risk. State plainly, for operators:

- Estimated hours no longer land on non-workdays, so **day and week totals change** even though no
  estimate was edited. Monthly and per-issue totals are unaffected.
- Per-member capacity is gone; the workspace max applies to everyone. Existing per-member values
  are **discarded, not migrated** — every workspace is seeded with the fixed 40h default (D8). They
  are **not recoverable**: the delete migration's reverse recreates an empty table only.
- Week columns now start on the configured day, and their API key format changed from `YYYY-Www`
  to the week's start date `YYYY-MM-DD`.
- The per-user "start of week" preference was removed; a workspace admin now sets it for everyone.

## Sibling-repo propagation (standing rule)

| Repo                                              | What                                                                                                                                                                                                                                                                                                                                         | Why                                                                                                                                |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| `plane-mcp-server`                                | New tools `get_work_settings` / `set_work_settings`; the workload tools' response now carries `tasks` + `tasks_truncated` (Phase 7). **Also:** the existing capacity gap — there is currently no capacity tool at all, so the removal breaks nothing, but the new settings must be reachable. Update any tool that returns week-bucket keys. | The MCP inventory exposes `get_workload`, `get_workload_rollups`, `set_issue_workload_estimate` — zero capacity/settings coverage. |
| `plane-node-sdk`                                  | Bindings for `GET                                                                                                                                                                                                                                                                                                                            | PUT /api/v1/workspaces/<slug>/work-settings/`; remove the capacity binding if one exists.                                          | Public API changed. |
| `plane-python-sdk`                                | Same.                                                                                                                                                                                                                                                                                                                                        | Same.                                                                                                                              |
| `plane-claude-plugin` / `docs` / `developer-docs` | Document the new settings endpoint and the week-key format change.                                                                                                                                                                                                                                                                           | Behaviour visible to API consumers.                                                                                                |

Use the `plane-propagate` skill; the sibling matrix and classification rule live in
`.claude/skills/plane-propagate/references/sibling-repos.md`.

Before opening anything: run the Phase 0 "Consumers of the week key" hit list against each sibling
repo — a consumer parsing `YYYY-Www` breaks silently, not loudly.

## Success criteria

- `docs/FORK.md` lists **every** file this feature touches outside a fork app, with a stated reason.
- A propagation issue or PR exists in each sibling repo named above, referenced from this PR body.
- `plane-fork-doctor` and `plane-isolation-audit` run clean.
- `python manage.py makemigrations --check --dry-run` and `pnpm check` clean on the final branch.
