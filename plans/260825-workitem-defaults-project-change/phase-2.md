# Phase 2 — Create modal: open prefill, project-change reset, post-fetch correction

Depends on phase 1.

## Ownership

Edited (fenced core-edit exception, row already exists in `docs/FORK.md`):

- `apps/web/core/components/issues/issue-modal/form.tsx`

Every change stays inside a `The1Studio fork (work-item creation defaults)` fence.

## Context the form must gather

Three store reads, all already available or one hook away:

```tsx
const { getProjectById } = useProject(); // already imported
const { data: currentUser } = useUser(); // already imported
const { fetchProjectMembers } = useProjectIssueProperties(); // same hook that gives fetchCycles
const {
  project: { getProjectMemberIds },
} = useMember(); // new import
```

`default_assignee` on `IProject` is typed `IUser | string | null`, so normalise it:
`typeof d === "string" ? d : (d?.id ?? null)`. Do not assume the string form.

Assignable ids come from `getProjectMemberIds(projectId, false)` — `false` excludes
`EUserPermissions.GUEST` (5), matching the server's `role >= 15` floor. It returns
`null` when the project's members have not been fetched; pass that `null` straight
through to the resolver, never coerce it to `[]`.

## The three sites

**1. `useForm` defaultValues (~line 160) and the mount reset (~line 209)** — replace
the `creationDefaults` memo's argument with the context object. At mount the member list
for the default project is usually cached (the project wrapper fetches it), and where it
is not, site 3 corrects it.

```tsx
const creationDefaults = useMemo(
  () => (data?.id ? {} : getWorkItemCreationDefaults(assigneeContext)),
  [data?.id, assigneeContextKey]
);
```

Keep the `data?.id` create-mode gate and keep spreading it AFTER
`DEFAULT_WORK_ITEM_FORM_VALUES` and BEFORE `...data` — a template, a duplicated item or
a group-derived value must still win.

**2. Project-change reset (~line 197)** — swap the helper:

```tsx
// The1Studio fork (work-item creation defaults) — getUpdateFormDataForReset drops
// assignee_ids by design; re-resolve it for the NEW project instead of emptying it.
reset(
  data?.id
    ? getUpdateFormDataForReset(projectId, getValues())
    : getProjectChangeFormReset(projectId, getValues(), assigneeContextForNewProject)
);
```

Edit mode keeps calling upstream's helper untouched. The template branch above it is dead
on this fork (`workItemTemplateId` is hardcoded `null` in
`apps/web/ce/components/issues/issue-modal/provider.tsx:36`) but leave it as-is —
narrowing it would widen the rebase diff for no gain.

Also add `fetchProjectMembers(workspaceSlug, projectId)` beside the existing
`fetchCycles` call in the same effect, so the correction pass below has something to wait
for. Guard it the same way (`if (projectId && routeProjectId !== projectId)`).

**3. Post-fetch correction (new effect)** — this is D4's second half:

```tsx
// The1Studio fork (work-item creation defaults) — the member list arrives after the
// project switch, so the optimistic assignee from site 2 has to be re-checked once
// it lands. Keyed on the JOINED ids: getProjectMemberIds is a computedFn returning a
// fresh array, and depending on its identity loops this effect.
const assignableMemberIds = projectId ? getProjectMemberIds(projectId, false) : null;
const assignableKey = assignableMemberIds?.join(",") ?? null;

useEffect(() => {
  if (data?.id || !projectId || assignableMemberIds === null) return;
  const current = getValues("assignee_ids") ?? [];
  const resolved = resolveCreationAssigneeIds({ ...ctx, currentAssigneeIds: current });
  if (resolved.length === current.length && resolved.every((id, i) => id === current[i])) return;
  setValue("assignee_ids", resolved, { shouldDirty: false });
}, [projectId, assignableKey]);
```

`shouldDirty: false` matters — a correction the user did not make must not arm the
unsaved-changes prompt on close. The equality guard matters for the same reason and
because it stops a re-render loop.

The effect cannot fight a manual pick: its deps change only on a project switch or a
member-list arrival, and the member dropdown fetches the list itself
(`apps/web/core/components/dropdowns/member/dropdown.tsx:43`) before the user can open it.

**"Create more" reset (~line 283)** already re-applies `creationDefaults`; it inherits
the project-aware version for free once site 1 changes. No separate edit.

## Verification (manual — no component harness exists for this modal)

1. Add work item, switch project → chip shows a valid assignee for the new project;
   name, description, priority, start date and due date all survive.
2. Pick a specific assignee who is a member of BOTH projects, switch → that pick is kept,
   not replaced by you.
3. Pick an assignee who is a member of only the FIRST project, switch → falls back to the
   new project's default assignee, else you, else empty.
4. Clear the due date, switch project → stays cleared. Switch again → still cleared.
5. Switch to a project you are not a member of → the chip never shows you.
6. Switch to a project whose members have never been fetched → the chip may show you for
   a beat, then settles on the correct value. It must SETTLE, not flicker repeatedly.
7. Open an existing work item and change its project → behaves exactly as before this
   change (upstream `getUpdateFormDataForReset`).
8. Toggle "Create more", save → the next blank form is prefilled for the project still
   selected, not the original one.

## Success criteria

- `pnpm check` clean.
- `pnpm turbo run build --filter=web` succeeds (the SSR prerender gate CI runs).
- All eight manual checks pass.
- Every added line sits inside a fork fence; `git diff` on this file shows no unfenced hunk.
