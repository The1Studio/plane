# Phase 3 — `base.tsx`: hold the value, write it once the work item exists

**Plan:** [plan.md](plan.md) · **Effort:** 2.5h · **Depends on:** phases [1](phase-1.md), [2](phase-2.md) · **Blocks:** phase 4

## Goal

Make the create-mode field actually save: wrap the modal in the pending-estimate provider, and PUT
the held hours immediately after the work item is created — before anything can turn it into a
parent.

## Ownership

```
apps/web/core/components/issues/issue-modal/base.tsx   (FENCED EDITS — the only file)
```

## Steps

### 1. Wrap the provider

`CreateUpdateIssueModalBase` renders either `DraftIssueLayout` or `IssueFormRoot` inside
`<ModalCore>`. Wrap **that pair**, so both paths are covered by one provider:

```tsx
{/* The1Studio fork (SP2 workload) — holds the create-mode "Estimated hours"
    draft, which cannot be PUT until the work item has an id. */}
<PendingEstimateProvider>
  {withDraftIssueWrapper ? <DraftIssueLayout … /> : <IssueFormRoot … />}
</PendingEstimateProvider>
```

The provider must sit **inside** `ModalCore` and outside both branches. Placing it around
`ModalCore` would keep state alive across closes; placing it in one branch would leave the other
throwing on `usePendingEstimate`.

### 2. Read the held value where the write happens

`CreateUpdateIssueModalBase` renders the provider, so it cannot also consume it. Phase 1's provider
is a controlled carrier for exactly this reason — the state lives here:

- Add `const [pendingHours, setPendingHours] = useState<string>("")` alongside the modal's existing
  `useState` block (`changesMade`, `createMore`, `activeProjectId`, …).
- Pass both into `<PendingEstimateProvider pendingHours={…} setPendingHours={…}>`.
- `handleCreateIssue` and `handleClose` then read and reset the state variable straight from their
  own closure, with no context read at all.

### 3. Write the estimate in `handleCreateIssue` (D7, D8)

Inside the existing `if (response.id && response.project_id) { … }` block, **before** the
`handleCreateSubWorkItem` call:

```tsx
// The1Studio fork (SP2 workload) — persist the create-mode estimate.
// MUST run before handleCreateSubWorkItem: that helper can give the new item
// children, and the backend rejects an estimate on a parent
// (PARENT_HAS_CHILDREN, apps/api/plane/workload/views.py). A failure here
// never fails the create — the work item exists and the success toast below
// still means what it says.
if (!is_draft_issue) {
  const hours = parseEstimateHoursInput(pendingHours, { allowEmpty: false });
  if (hours !== null) {
    try {
      await workloadStore.updateEstimate(workspaceSlug.toString(), response.project_id, response.id, hours);
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: wlt("estimate.create_failed_toast_title"),
        message: wlt("estimate.create_failed_toast_message"),
      });
    }
  }
}
```

`allowEmpty: false` is the whole empty-field contract: an untouched field is `""`, parses to `null`,
and writes nothing — no `0` row is created for every work item made without an estimate.

`workloadStore` comes from `useWorkload()`, added alongside the existing store hooks at the top of
the component.

### 4. Warn on the save-as-draft path (D6)

`handleCreateIssue(payload, true)` runs from `handleClose` when the user discards with changes, and
from `DraftIssueLayout`'s own draft save. In the `is_draft_issue` branch, when `pendingHours` parses
to a non-null number, raise exactly one warning toast:

```tsx
setToast({
  type: TOAST_TYPE.WARNING,
  title: wlt("estimate.draft_not_saved_toast_title"),
  message: wlt("estimate.draft_not_saved_toast_message"),
});
```

Then fall through as normal. The draft is still saved; only the hours are dropped, and the user is
told. Do not block the draft save.

### 5. Reset (D11)

- **After a successful create**, in the same block that already does `setDescription("<p></p>")` and
  `setChangesMade(null)`: reset pending hours to `""`. This is what stops "Create more" from
  silently giving item N+1 item N's estimate.
- **In `handleClose`**, beside the existing `setActiveProjectId(null)` / `setChangesMade(null)`:
  reset as well, so reopening the modal starts clean.
- **Do NOT** reset on project change. Hours are project-independent, and the form's
  `reset(getUpdateFormDataForReset(...))` on project switch must not take them with it — the value
  lives outside react-hook-form precisely so it is not swept by that reset.

## Success criteria

Each maps to a decision; verify by observation, not by reading the diff.

| #   | Check                                                                                                                                                                                                 | Proves                           |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| 1   | Create with `4.5` → the spreadsheet's Estimated-hours column reads `4.5` for the new item                                                                                                             | D2                               |
| 2   | Create with the field untouched → `GET /workload-estimates/` returns no row for it; the column is blank, not `0`                                                                                      | D2, step 3's `allowEmpty: false` |
| 3   | "Create more" on: create with `3`, then create a second with the field cleared → the second has **no** estimate                                                                                       | D11                              |
| 4   | "Create more" on: create with `3`, then a second with `8` → 3 and 8, not 8 and 8                                                                                                                      | D11                              |
| 5   | Type hours, switch project mid-form, then create → the hours still land                                                                                                                               | D11's no-reset-on-project-change |
| 6   | Type hours, press Discard on a modal with a title → draft-not-saved warning toast, draft saved                                                                                                        | D6                               |
| 7   | Create while offline (devtools throttle to offline after the POST resolves, or point the PUT at a 500) → work item created, success toast, **plus** the estimate-failed toast; no crash, modal closes | D8                               |

Plus `pnpm check` and `pnpm turbo run build --filter=web`.

## Do not

- Add the hours to the `payload` passed to `createIssue`. The core `POST /issues/` serializer has no
  such field and would ignore or reject it; the estimate is a separate table and a separate request.
- Make the create `await` fail on an estimate error (D8).
- Reset pending hours inside `IssueFormRoot`'s `reset(...)` calls — that is react-hook-form's scope
  and this value is deliberately outside it.
- Touch `handleUpdateIssue`. Update mode already saves through the editor hook (D1); adding a second
  write there would double-PUT.
