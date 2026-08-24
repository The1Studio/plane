# Phase 6 — Quick-add prefill (all four layouts)

Depends on phase 5 for `getWorkItemCreationDefaults`.

Implements D4. Without it, inline-added items would get today's due date from the backend but no assignee — `createIssuePayload` (`packages/utils/src/work-item/base.ts:153`) hardcodes `assignee_ids: []`, which D2 reads as a deliberate "nobody". Two create surfaces would then disagree for a reason no user can see.

## Ownership

Edited (fenced core-edit exception):

- `apps/web/core/components/issues/issue-layouts/quick-add/root.tsx`

One file covers all four layouts — list, kanban, calendar and spreadsheet all render `QuickAddIssueRoot`. Confirm this before widening the edit: `grep -rln "QuickAddIssueRoot" apps/web/core/components/issues/issue-layouts/`.

## Edit

In `onSubmitHandler` (~line 105), inject the defaults **between** `prePopulatedData` and `formData`:

```tsx
// The1Studio fork (work-item creation defaults) — inline add gets the same
// creator + today's-due-date prefill as the Add-work-item modal.
const payload = createIssuePayload(projectId.toString(), {
  ...(prePopulatedData ?? {}),
  ...getWorkItemCreationDefaults(currentUser?.id),
  ...formData,
});
```

Ordering matters in both directions. Placing it after `prePopulatedData` would overwrite a group-derived value — the calendar's quick-add prepopulates `target_date` from the clicked day, and dropping that would put every calendar-added item on today instead of the day the user clicked. Placing it before `formData` keeps anything the user actually typed.

`prePopulatedData` may also carry `assignee_ids` when adding inside an assignee-grouped kanban column; that must win over the creator for the same reason.

`currentUser` from `useUser()`, imported alongside the existing hooks.

## Tests

No unit harness exists for this component. Manual verification per layout:

- **list** — inline add → assigned to creator, due today
- **kanban grouped by assignee** — add inside another member's column → assigned to THAT member, not the creator
- **calendar** — add on a future day → due that day, not today
- **spreadsheet** — inline add → assigned to creator, due today

The kanban and calendar cases are the ones the ordering above exists for; treat them as blocking, not spot checks.

## Success criteria

- `pnpm check` clean.
- All four layouts create assigned, dated items.
- Group-derived assignee and date still win over the defaults.
