# Phase 1 — Project-aware resolver in `packages/work-item-defaults-ext`

All the judgment moves into the fork-owned package as pure functions, so `form.tsx` and
quick-add keep one fenced call each and the rules are unit-testable without a component
harness (none exists for this modal).

## Ownership

Edited:

- `packages/work-item-defaults-ext/src/creation-defaults.ts`
- `packages/work-item-defaults-ext/src/index.ts` (only if new files are added)
- `packages/work-item-defaults-ext/src/__tests__/creation-defaults.test.ts`

Created:

- `packages/work-item-defaults-ext/src/project-change.ts` + its test file

Nothing outside `packages/work-item-defaults-ext/` is touched in this phase.

## API

```ts
export type TCreationAssigneeContext = {
  /** Current form value. Absent/empty at modal open. */
  currentAssigneeIds?: string[] | null;
  currentUserId?: string | null;
  /** The chosen project's own default assignee, already normalised to an id. */
  projectDefaultAssigneeId?: string | null;
  /**
   * Assignable member ids for the chosen project — `getProjectMemberIds(id, false)`.
   * `null` means NOT FETCHED YET, and is deliberately distinct from `[]`
   * (fetched, nobody assignable). D4 turns on that distinction.
   */
  assignableMemberIds?: string[] | null;
};

export const resolveCreationAssigneeIds = (ctx: TCreationAssigneeContext): string[];
```

Resolution order — this is D1 plus the server's own order in
`plane/issue_defaults_ext/defaults.py:resolve_creation_assignee_id`:

1. `assignableMemberIds == null` (not fetched): **optimistic**. Return
   `currentAssigneeIds` when non-empty; else `projectDefaultAssigneeId` when set;
   else `currentUserId` when set; else `[]`. Assignability is unknown here, so nothing
   is filtered — phase 2's correction pass fixes it once the list lands.
2. Otherwise **filter**: `kept = currentAssigneeIds.filter(id => assignable.includes(id))`.
   Return `kept` when non-empty — a deliberate pick that is still valid always wins.
3. Fallback, in order: `projectDefaultAssigneeId` if assignable → `currentUserId` if
   assignable → `[]`.

Never returns an array containing `undefined`/`null`/`""`, mirroring the existing
"half-hydrated store" guard.

```ts
export const getWorkItemCreationDefaults = (ctx: TCreationAssigneeContext): Partial<TIssue>;
```

Signature change (D3): it now takes the same context object instead of a bare user id,
and its `assignee_ids` comes from `resolveCreationAssigneeIds`. `target_date` is
unchanged — `renderFormattedPayloadDate(new Date())`. When the resolver yields `[]`
**and** no user is loaded, keep returning `{}` so a half-hydrated store still cannot
produce a form that says "deliberately empty".

Note the asymmetry and keep it: `assignee_ids: []` from a _resolved_ context is a real
value (nobody is assignable) and must be emitted; `{}` is only for the not-loaded case.

```ts
export const getProjectChangeFormReset = (
  projectId: string | null | undefined,
  formValues: Partial<TIssue>,
  ctx: TCreationAssigneeContext,
): Partial<TIssue>;
```

Wraps `getUpdateFormDataForReset` from `@plane/utils` (already a dependency) and overrides
`assignee_ids` with `resolveCreationAssigneeIds`. Existing as a wrapper rather than a
patch is the point: `packages/utils` is a sealed `@plane/*` package per `docs/FORK.md`,
and this keeps the date carry-forward it owns testable from fork-owned code.

## Tests

`resolveCreationAssigneeIds`:

- kept pick wins — current `["u1"]`, assignable `["u1","u2"]`, default `"u2"` → `["u1"]`
- partially-valid pick is narrowed, not discarded — `["u1","u9"]` with assignable
  `["u1"]` → `["u1"]`
- invalid pick falls back to the project default — `["u9"]`, assignable `["u1","u2"]`,
  default `"u2"` → `["u2"]`
- no default → creator, when assignable
- creator not assignable and no default → `[]`
- default assignee set but NOT assignable → skipped, creator used (mirrors `_is_assignable`)
- `assignableMemberIds: null` → optimistic: current pick, else default, else creator,
  and **no filtering happens** — `["u9"]` survives while the list is unfetched
- `assignableMemberIds: []` (fetched, none assignable) → `[]`, distinct from the `null` case
- never contains `undefined`, `null` or `""`

`getWorkItemCreationDefaults`:

- keeps the existing three cases (creator + today; `{}` for an unloaded user; no
  `undefined` in the array), rewritten for the context argument
- project-aware: a creator absent from `assignableMemberIds` yields `assignee_ids: []`
  while `target_date` is still today

`getProjectChangeFormReset`:

- **D2 regression pin** — `start_date` and `target_date` present in `formValues` come
  through byte-identical, and a `null` `target_date` stays `null` rather than being
  re-filled with today. This is the test that would go red if a future edit made the
  reset re-assert the date default.
- `name`, `description_html`, `priority` still carried (guards against an upstream
  change to `getUpdateFormDataForReset` silently narrowing what survives)
- `state_id`, `label_ids`, `cycle_id`, `module_ids` still reset — the project-scoped
  fields must keep clearing
- `assignee_ids` reflects the resolver, not `[]`

## Success criteria

- `pnpm --filter @plane/work-item-defaults-ext test` green.
- `pnpm --filter @plane/work-item-defaults-ext check:types` clean.
- No import of anything under `apps/` from this package.
