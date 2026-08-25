# Phase 4 — Documentation, isolation audit, end-to-end verification

Depends on phases 1–3.

## Ownership

Edited:

- `docs/FORK.md` — amend the two existing rows in the "Work-item creation defaults" table
- `CLAUDE.md` — amend the `issue_defaults_ext/` bullet

No new FORK.md rows: `form.tsx` and `quick-add/root.tsx` are already listed as fenced
core-edit exceptions (`docs/FORK.md:803-804`). Their "What" cells describe a bare
`getWorkItemCreationDefaults(currentUser?.id)` spread, which stops being true here.

## `docs/FORK.md`

In the § "Work-item creation defaults" behaviour list, add one bullet next to the
existing "A creator who is not an assignable project member is skipped":

> **The modal's prefill is project-aware, and survives a project change.** Switching
> project inside the create modal keeps assignees who are still assignable in the new
> project, and otherwise re-resolves in the server's own order — the new project's
> `default_assignee`, then the creator, then nobody. Dates are carried across untouched
> and a cleared due date is never re-filled. The resolution lives in
> `packages/work-item-defaults-ext`; `form.tsx` calls it and holds no rules of its own.

Amend the `form.tsx` row's "What" to name the three sites (open prefill, project-change
reset via `getProjectChangeFormReset`, post-fetch correction effect) and the `quick-add`
row's to say the helper is now project-aware while the spread order is unchanged.

Record the dead template branch as a known fork fact, since a reader will otherwise
assume it is live: `workItemTemplateId` is hardcoded `null` in
`apps/web/ce/components/issues/issue-modal/provider.tsx:36`, so of the project-change
effect's two branches only the `else` ever runs on this fork.

## `CLAUDE.md`

Extend the `issue_defaults_ext/` bullet with the frontend behaviour — that the create
modal re-resolves the assignee on a project change rather than clearing it, that a
kept-but-still-valid pick wins over the default, and that dates carry across a project
change and a cleared due date is never re-filled. Say plainly that **`start_date` has
never had a default** on either side, so "the start date reset" is not a behaviour this
feature ever provided.

## Isolation audit

Run the `plane-isolation-audit` skill. Expected: zero new core-edit findings — all new
logic is inside `packages/work-item-defaults-ext`, which the FORK.md note already
allowlists as fork-owned despite its `@plane/` scope.

## Propagation

Per the standing rule in `CLAUDE.md`, check every downstream surface and record the
result. Expected outcome: **nothing to propagate**. No endpoint, field, or serializer
behaviour changed — `issue_defaults_ext/defaults.py` and both core serializers are
untouched, so `plane-mcp-server`, `plane-node-sdk`, `plane-python-sdk` and the docs repos
see an identical API. State this explicitly in the PR body rather than leaving it
unaddressed; a silent omission reads the same as a forgotten propagation.

## Full verification

- `pnpm check`
- `pnpm turbo run test` (includes the phase-1 suite; already gated by
  `.github/workflows/company-main-ci.yml` job 2)
- `pnpm turbo run build --filter=web`
- The eight manual checks from phase 2 and the four from phase 3, run once more against
  the built app rather than the dev server.

## Success criteria

- Both docs amended; `docs/FORK.md` still passes `plane-fork-doctor`.
- Isolation audit clean.
- Propagation outcome stated in the PR body.
- CI green on the PR, then babysit to green and admin-merge per standing practice.
