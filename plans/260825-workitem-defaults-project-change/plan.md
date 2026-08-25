# Work-item creation defaults survive a project change

The create modal prefills the creator as assignee and today as the due date
(`plans/260824-workitem-creation-defaults/`). Changing the project from the modal's
project dropdown drops the assignee, and the prefill has never been project-aware —
it can name an assignee the chosen project would reject.

## Root cause

`apps/web/core/components/issues/issue-modal/form.tsx:188-203` — the project-change
effect has two branches:

```tsx
if (isDirty) {
  if (workItemTemplateId) {
    reset({ ...DEFAULT_WORK_ITEM_FORM_VALUES, ...creationDefaults, project_id: projectId });
  } else {
    reset(getUpdateFormDataForReset(projectId, getValues())); // <-- the live path
  }
}
```

`workItemTemplateId` is hardcoded `null` in CE (`apps/web/ce/components/issues/issue-modal/provider.tsx:36`),
so **the template branch never runs on this fork** and the `else` is the only live path.
`getUpdateFormDataForReset` (`packages/utils/src/work-item/modal.ts:12`) rebuilds the form
from `DEFAULT_WORK_ITEM_FORM_VALUES` and carries forward exactly five fields —
`name`, `description_html`, `priority`, `start_date`, `target_date`. `assignee_ids`
falls back to `[]`, and `creationDefaults` is never re-applied on this branch.

**Dates are not part of the bug.** Both `start_date` and `target_date` are explicitly
carried forward by that helper, and the fork has never defaulted `start_date` at all —
`issue_defaults_ext/defaults.py` defaults one assignee and `target_date` only. Phase 1
pins the date carry-forward with a test so this stays true, but no date code changes.

## Second defect, same root

`getWorkItemCreationDefaults(currentUserId)` takes only a user id. It prefills the
creator as assignee for **any** project, including one where they are not an assignable
member. The core serializer validates assignees against project membership, so that
prefill can produce a rejected create — the exact case `issue_defaults_ext` already
guards on the server (`_is_assignable`, `ASSIGNABLE_ROLE_FLOOR = 15`).

## Decisions

| #   | Decision                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | On a project change, keep the assignees already selected when they are still assignable in the new project. Only when none survive does the backend fallback order apply: the new project's `default_assignee` if assignable, else the creator if assignable, else empty. |
| D2  | Dates are preserved across a project change and a cleared field is **never** re-filled. This is today's behaviour; phase 1 pins it with a regression test.                                                                                                                |
| D3  | The opening prefill becomes project-aware too, using the same resolver — not just the project-change path. This closes the rejected-assignee case above.                                                                                                                  |
| D4  | When the new project's member list is not cached, apply optimistically (keep the current pick, else the creator) and correct once `fetchProjectMembers` resolves. A briefly-shown chip that then disappears is accepted; a silently-absent default is not.                |

Assignability is read as `getProjectMemberIds(projectId, /* includeGuestUsers */ false)`,
which filters `EUserPermissions.GUEST` (5) and so matches the server's `role >= 15` floor.
`null` from that call means "not fetched yet", not "no members" — D4 exists because of it.

## Scope

Frontend only. `issue_defaults_ext` and both serializers are unchanged, so there is
nothing to propagate to `plane-mcp-server` or the SDKs; the API contract is identical.
`packages/utils` and `packages/constants` are sealed `@plane/*` packages and are not
touched — the assignee is re-applied _after_ `getUpdateFormDataForReset`, never inside it.

## Phases

| Phase           | Goal                                                                                        | Effort  |
| --------------- | ------------------------------------------------------------------------------------------- | ------- |
| [1](phase-1.md) | Project-aware resolver + reset helper in `packages/work-item-defaults-ext`, with unit tests | S (~3h) |
| [2](phase-2.md) | Wire the create modal: open prefill, project-change reset, post-fetch correction            | S (~3h) |
| [3](phase-3.md) | Wire inline quick-add to the same resolver                                                  | S (~2h) |
| [4](phase-4.md) | `docs/FORK.md` + `CLAUDE.md` amendments, isolation audit, end-to-end verification           | S (~2h) |

Total ~10h. Critical path is 1 → 2; phase 3 depends only on phase 1, phase 4 on all.

## Ownership (zero overlap)

| Path                                                               | Phase |
| ------------------------------------------------------------------ | ----- |
| `packages/work-item-defaults-ext/**`                               | 1     |
| `apps/web/core/components/issues/issue-modal/form.tsx`             | 2     |
| `apps/web/core/components/issues/issue-layouts/quick-add/root.tsx` | 3     |
| `docs/FORK.md`, `CLAUDE.md`, `.claude/skills/**`                   | 4     |

## Risk Assessment

| Risk                                                                                                            | L   | I   | Score | Mitigation                                                                                                                                                     |
| --------------------------------------------------------------------------------------------------------------- | --- | --- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The post-fetch correction effect loops, because `getProjectMemberIds` is a `computedFn` returning a fresh array | 3   | 4   | 12    | Key the effect on a joined-id string, never the array identity; assert idempotence in the phase-2 manual check                                                 |
| The correction pass overwrites an assignee the user just picked                                                 | 2   | 4   | 8     | Deps are `[projectId, memberIdsKey]` only, so a manual pick after load cannot retrigger it; the member dropdown fetches members itself before it can be opened |
| `getProjectMemberIds` does not filter `is_active`, so a deactivated member could be treated as assignable       | 2   | 2   | 4     | The server re-validates on create; a rejected assignee surfaces as a normal form error, not silent data loss                                                   |
| Changing `getWorkItemCreationDefaults`'s signature breaks a call site                                           | 2   | 3   | 6     | Private workspace package, exactly two call sites, both rewritten in this plan; `pnpm check` is the gate                                                       |
| Rebase conflict widens in `form.tsx`                                                                            | 2   | 3   | 6     | All new code stays inside the existing `The1Studio fork (work-item creation defaults)` fences; logic lives in the fork-owned package                           |

## Success criteria

- Open Add work item, switch project: the assignee chip shows a valid assignee for the
  new project (kept pick if still a member, else project default, else you, else empty)
  and both date fields keep whatever they held.
- Clear the due date, then switch project: it stays cleared.
- Switch to a project you are not a member of: the chip resolves to that project's
  default assignee or empties — it never shows you.
- Edit an existing work item: no field is touched on a project change beyond upstream's
  own behaviour.
- `pnpm check` clean; `pnpm turbo run test` green (the package's suite is already gated
  by `.github/workflows/company-main-ci.yml` job 2).

## Cook handoff

`/t1k:cook plans/260825-workitem-defaults-project-change/plan.md`
