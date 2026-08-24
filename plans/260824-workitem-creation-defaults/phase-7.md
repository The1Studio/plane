# Phase 7 — Fork documentation

Depends on phases 3–6. Required by the fork discipline: a fenced core edit that is not recorded in `docs/FORK.md` is indistinguishable from a leak at the next rebase, and `plane-isolation-audit` will report it as one.

## Ownership

Edited:

- `docs/FORK.md` — new subsection under § "Frontend core-edit exceptions"; new bullet under § "Backend customizations"; row(s) in the core-edit exception table
- `CLAUDE.md` — new bullet in § "Custom features (fork-owned)"

## `docs/FORK.md`

**Backend customizations** — add `issue_defaults_ext` to the app list, stating that it is model-less (no `migrations/`, like `workspace_ext`) and exposes no endpoint (no touch-point 2 entry).

**New subsection** `### Work-item creation defaults — fenced \`The1Studio fork (work-item creation defaults)\``, with the per-file exception table every other subsection in that section uses. Six rows:

| File | Why no upstream seam |
|---|---|
| `app/serializers/issue.py` | Only the serializer can distinguish an absent field from an explicit null; a signal sees `None` for both |
| `app/views/intake/base.py` | Context flag is the only way to opt one caller out |
| `api/serializers/issue.py` | Same, public API path; field is spelled `assignees` |
| `apps/web/.../issue-modal/form.tsx` | `DEFAULT_WORK_ITEM_FORM_VALUES` lives in the sealed `@plane/constants` |
| `apps/web/.../quick-add/root.tsx` | `createIssuePayload` hardcodes `assignee_ids: []` in sealed `@plane/utils` |
| `apps/web/package.json` | Touch-point 6, designed seam — not an exception, listed for completeness |

Record the behavior itself, not just the file list — the absent-vs-explicit-empty rule, the project-default-first precedence, the `max(today, start_date)` rule, and the creator's-timezone basis for "today". A future reader hitting a rebase conflict in one of these files needs to know what the code was protecting.

## `CLAUDE.md`

One bullet in § "Custom features (fork-owned)":

> `issue_defaults_ext/` — creation defaults for work items. A create payload that omits `assignee_ids` / `assignees` gets the creator (the project's `default_assignee` still takes precedence, and a creator who is not an active project member with `role >= 15` is skipped); one that omits `target_date` gets today in the **creator's** `user_timezone`, or `start_date` when that is later, so a future start date can never produce the "Start date cannot exceed target date" error. An explicit `[]` or `null` is a deliberate "nobody" / "no due date" and is never overwritten — including on update, where no default ever applies. Intake creation is excluded via an `apply_creation_defaults: False` serializer context; raw-ORM writers (the ClickUp loaders) never reach a serializer and are excluded structurally. Drafts, sub-work-items and epics are in scope. Frontend: `packages/work-item-defaults-ext` prefills the create modal and inline quick-add so the values are visible and clearable; a group-derived assignee or date (kanban assignee column, calendar day) still wins.

## Success criteria

- `plane-isolation-audit` reports zero unaccounted core edits.
- Every file edited in phases 3–6 appears in the `docs/FORK.md` exception table.
- The `CLAUDE.md` bullet states the absent-vs-empty rule explicitly — it is the part an SDK or MCP consumer will otherwise get wrong.
