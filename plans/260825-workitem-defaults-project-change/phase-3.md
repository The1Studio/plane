# Phase 3 — Inline quick-add uses the same resolver

Depends on phase 1 only. Independent of phase 2 — different file, no shared state.

## Why quick-add is in scope at all

Quick-add has no project dropdown, so it cannot hit the project-change bug. It is here
for D3: it calls the same `getWorkItemCreationDefaults`, whose signature changes in
phase 1, and it has the same latent defect — it prefills the creator as assignee for the
route project without checking membership. A workspace-level layout can reach a project
the viewer is not an assignable member of.

## Ownership

Edited (fenced core-edit exception, row already exists in `docs/FORK.md`):

- `apps/web/core/components/issues/issue-layouts/quick-add/root.tsx`

## Change

`onSubmitHandler` builds the payload as:

```tsx
const payload = createIssuePayload(projectId.toString(), {
  ...getWorkItemCreationDefaults(assigneeContext),
  ...(prePopulatedData ?? {}),
  ...formData,
});
```

Only the argument changes. **The spread ORDER is load-bearing and must not move** — the
defaults go first so a later spread wins: the calendar prepopulates `target_date` from
the clicked day and an assignee-grouped kanban column prepopulates `assignee_ids`, and
both must beat the defaults. The existing comment above this call says so; keep it.

The context is built from the route `projectId`:

```tsx
const {
  project: { getProjectMemberIds },
} = useMember();
const { getProjectById } = useProject();
```

No optimistic/correction split is needed here. Quick-add is only reachable inside a
project layout, whose wrapper already fetched that project's members
(`apps/web/core/layouts/auth-layout/project-wrapper.tsx:101`), so
`getProjectMemberIds` is populated by the time a payload can be submitted. If it is
still `null`, the resolver's optimistic branch applies and the server re-validates —
which is the same outcome as today, not a regression.

`prePopulatedData.assignee_ids` from an assignee-grouped column is NOT filtered by the
resolver: it is spread after the defaults, so it overrides them wholesale. That is
correct — the column's own value is an explicit user intent, and the server validates it.

## Verification

1. Inline-add in a project where you are a member → assigned to you, due today.
2. Inline-add in an assignee-grouped kanban column → assigned to that column's member,
   not to you.
3. Inline-add on the calendar layout on a future day → due date is that day, not today.
4. Inline-add in a project where you are a Guest → created unassigned rather than
   rejected.

## Success criteria

- `pnpm check` clean.
- All four checks pass; checks 2 and 3 are the ordering regression guards.
