# Phase 5 — `work-item-defaults-ext` package + create-modal prefill

Delivers the visible half of D1: the modal opens with the assignee chip and due-date pill already filled, and the user can change or clear either before saving.

Without this phase the backend alone does nothing for the modal — `DEFAULT_WORK_ITEM_FORM_VALUES` sets `assignee_ids: []` and `target_date: null`, so under D2 the modal always sends explicit "deliberately empty" values and never reaches the backend's absent path.

## Ownership

Created (fork-owned package):

- `packages/work-item-defaults-ext/package.json`
- `packages/work-item-defaults-ext/tsconfig.json`
- `packages/work-item-defaults-ext/src/index.ts`
- `packages/work-item-defaults-ext/src/creation-defaults.ts`
- `packages/work-item-defaults-ext/src/creation-defaults.spec.ts`

Edited (touch-point 6, designed seam):

- `apps/web/package.json` — `"@plane/work-item-defaults-ext": "workspace:*"`

Edited (fenced core-edit exceptions):

- `apps/web/core/components/issues/issue-modal/form.tsx` — three `DEFAULT_WORK_ITEM_FORM_VALUES` sites (~143, ~176, ~190) and the `useForm` initialisation

A new package rather than an inline helper because `packages/constants` is a sealed `@plane/*` package and `docs/FORK.md` § "Frontend customizations" requires new frontend code to live in a new package. It also gives phase 6 something to import instead of duplicating the shape.

## API

```ts
// packages/work-item-defaults-ext/src/creation-defaults.ts
export const getWorkItemCreationDefaults = (currentUserId: string | undefined): Partial<TIssue>
```

Returns `{ assignee_ids: [currentUserId], target_date: renderFormattedPayloadDate(new Date()) }`, and `{}` when `currentUserId` is undefined — a half-loaded user must not produce `assignee_ids: [undefined]`.

`renderFormattedPayloadDate` from `@plane/utils` is the same helper the date dropdown already uses, so the string format matches what the form would have produced by hand. It reads the browser's local date, which is why D8 pins the backend to the creator's `user_timezone` — the two must agree.

## Wiring

The prefill applies **only in create mode**. The modal is shared with edit (`base.tsx` distinguishes them by `data?.id`). Guard every site:

```tsx
// The1Studio fork (work-item creation defaults) — prefill the creator and
// today's due date on create only; an edit must never re-fill a cleared field.
const creationDefaults = useMemo(
  () => (data?.id ? {} : getWorkItemCreationDefaults(currentUser?.id)),
  [data?.id, currentUser?.id]
);
```

Spread it **after** `DEFAULT_WORK_ITEM_FORM_VALUES` and **before** `...data`, so a caller-supplied value (a template, a prepopulated group value, a duplicated work item) still wins:

```tsx
defaultValues: { ...DEFAULT_WORK_ITEM_FORM_VALUES, ...creationDefaults, project_id: defaultProjectId, ...data },
```

The same ordering applies at the project-change reset (~176) and the data reset (~190). `getUpdateFormDataForReset` (`packages/utils/src/work-item/modal.ts`) already carries `target_date` forward across a project change, so that path needs no change — but it drops `assignee_ids` by design (assignees are project-scoped), and after a project switch the chip will be empty. That is correct: the creator may not be a member of the newly chosen project, and the backend will not assign a non-member either.

`currentUser` comes from `useUser()`, already used throughout `apps/web/core/components/issues/`.

## Tests

`creation-defaults.spec.ts`:

- returns the creator id and today's date for a known user
- returns `{}` for `undefined`, and never an array containing `undefined`
- the date string matches `renderFormattedPayloadDate(new Date())` exactly

Manual verification (no component test harness exists for this modal):

- open Add work item → chip shows the current user, pill shows today
- clear both, save → item is unassigned with no due date, confirming D2 end to end
- open an existing item for edit → neither field is touched, and closing without changes raises no unsaved-changes prompt
- switch project inside the modal → no crash, due date preserved

## Success criteria

- `pnpm check` clean.
- Create modal opens prefilled; both values clearable and the cleared state persists.
- Edit modal unaffected.
