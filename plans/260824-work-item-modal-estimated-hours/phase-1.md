# Phase 1 — `packages/workload-ext`: parse helper + pending-estimate context

**Plan:** [plan.md](plan.md) · **Effort:** 2h · **Depends on:** nothing · **Blocks:** phases 2, 3

## Goal

Add the two fork-owned primitives the modal needs, both in `packages/workload-ext` (fork-owned; the
`@plane/` scope on this package is **not** an upstream package — editing it is not a sealed-package
violation, per `docs/FORK.md`):

1. `parseEstimateHoursInput` — the single place a raw input string becomes a committable number.
2. `PendingEstimateProvider` / `usePendingEstimate` — holds the create-mode draft value.

Neither touches `useWorkload()`, so both belong in the package rather than in core.

## Ownership

Only these paths:

```
packages/workload-ext/src/estimateInput.ts             (NEW)
packages/workload-ext/src/PendingEstimate.tsx          (NEW)
packages/workload-ext/src/__tests__/estimateInput.test.ts  (NEW)
packages/workload-ext/src/index.ts                     (add exports)
packages/workload-ext/src/i18n.ts                      (add string keys)
packages/workload-ext/package.json                     (add the `test` script + vitest devDeps)
apps/web/core/hooks/store/use-workload-estimate-editor.ts  (parse step only — see step 4)
```

## Steps

### 1. `estimateInput.ts`

Transcribe the branch order **exactly** as it exists today in `use-workload-estimate-editor.ts`'s
`commit`, so the extraction is behavior-preserving:

```ts
/**
 * Parse a raw "Estimated hours" input string into a committable number.
 *
 * SSOT for every hours input in the fork — the modal's create-mode field and
 * `useWorkloadEstimateEditor`'s commit step both call this, so the two paths
 * cannot drift on what counts as a valid number.
 *
 * Returns `null` when the raw value must NOT be committed:
 *   - empty and `allowEmpty` is false (clearing the field to retype must never
 *     write a 0),
 *   - not a finite number,
 *   - negative.
 * An empty string with `allowEmpty: true` parses to 0 — an explicit Enter or
 * blur is how a user clears an estimate.
 *
 * The upper bound (MAX_HOURS) is deliberately NOT enforced here: it is the
 * server's, and `WorkloadEstimateSerializer.validate_hours` returns a real
 * error for it. Silently clamping client-side would hide a typo.
 */
export function parseEstimateHoursInput(raw: string, options: { allowEmpty: boolean }): number | null;
```

Implementation, in this order: `raw.trim()` → if `""` and `!allowEmpty` return `null` → `parsed =
trimmed === "" ? 0 : Number(trimmed)` → if `!Number.isFinite(parsed) || parsed < 0` return `null` →
return `parsed`.

### 2. `PendingEstimate.tsx`

A minimal context, deliberately storing the **raw string** rather than a number — the draft must be
able to hold the intermediate `"12."` a user types on the way to `12.5`, the same reason the editor
hook's draft is a string.

```tsx
type TPendingEstimateContext = {
  /** Raw draft string for a work item that does not exist yet. "" means untouched. */
  pendingHours: string;
  setPendingHours: (raw: string) => void;
};

type TPendingEstimateProviderProps = TPendingEstimateContext & { children: React.ReactNode };
```

- **The provider is a controlled carrier, not a state owner.** It takes `pendingHours` and
  `setPendingHours` as props and does nothing but `useMemo` them into a context value. The
  `useState` lives one level up, in `CreateUpdateIssueModalBase` — phase 3 needs to read the value
  in `handleCreateIssue` and reset it in `handleClose`, and a component cannot consume a context it
  renders. There is no internal-`useState` variant of this provider; do not add one.
- No `resetPendingHours` on the context: the owner resets by calling its own setter with `""`.
- `usePendingEstimate()` throws a named error when used outside the provider — a silent no-op
  context would make a mis-wired provider look like "the field just doesn't save"
  (`development-principles.md` § "Errors Over Silent Fallbacks").
- Header comment states that this holds create-mode state ONLY; update mode goes through
  `useWorkloadEstimateEditor` and never touches this context.

### 3. Strings + exports

`i18n.ts` — add under the existing `estimate.*` block:

```
"estimate.placeholder": "Hours",
"estimate.draft_not_saved_toast_title": "Estimated hours not saved",
"estimate.draft_not_saved_toast_message": "Drafts can't carry an estimate. Set it once the work item is in a project.",
"estimate.create_failed_toast_title": "Estimated hours not saved",
"estimate.create_failed_toast_message": "The work item was created, but its estimate couldn't be saved. Set it from the work item.",
```

`index.ts` — export `parseEstimateHoursInput`, `PendingEstimateProvider`, `usePendingEstimate`, and
the `TPendingEstimateContext` type.

### 4. Point the existing hook at the helper

In `use-workload-estimate-editor.ts`'s `commit`, replace the inline trim/empty/`Number`/finite/
negative block with:

```ts
const parsed = parseEstimateHoursInput(raw, { allowEmpty: options.allowEmpty });
if (parsed === null) return;
```

Everything after it — the `pendingValueRef` dedupe, `setIsSaving`, the `PARENT_HAS_CHILDREN`
backstop — is untouched. The file already carries a fork-exception header; no new fence is needed.

### 5. Test wiring

`package.json`: add `"test": "vitest run"` and `"test:watch": "vitest"`, mirroring
`packages/cascade-ext/package.json`, plus the same vitest devDependencies that package declares.

`__tests__/estimateInput.test.ts` covers, at minimum:

| Input        | `allowEmpty` | Expected                                                                  |
| ------------ | ------------ | ------------------------------------------------------------------------- |
| `"4"`        | false        | `4`                                                                       |
| `"4.5"`      | false        | `4.5`                                                                     |
| `" 4.5 "`    | false        | `4.5`                                                                     |
| `"12."`      | false        | `12`                                                                      |
| `""`         | false        | `null` — the clearing-to-retype guard                                     |
| `""`         | true         | `0` — explicit clear                                                      |
| `"   "`      | false        | `null`                                                                    |
| `"abc"`      | true         | `null`                                                                    |
| `"-1"`       | true         | `null`                                                                    |
| `"1e3"`      | false        | `1000` — documents that `Number` accepts it, matching today's behavior    |
| `"99999999"` | false        | `99999999` — documents that the client does NOT clamp; the server rejects |

The last two rows are **characterization** assertions: they record what the current code does, not
what it ideally should. Comment them as such so a future reader does not mistake them for a spec.

## Success criteria

- `pnpm --filter @plane/workload-ext test` — all green.
- `pnpm check` — clean.
- `grep -n "trim()" apps/web/core/hooks/store/use-workload-estimate-editor.ts` returns nothing:
  the duplicate is gone, not merely joined by a copy.
- Existing behavior unchanged: type `12.` in a spreadsheet Estimated-hours cell, wait, and it still
  commits as `12`; clear a cell and it still does **not** auto-write `0`.

## Do not

- Enforce `MAX_HOURS` client-side.
- Change the debounce interval, the Enter-keeps-focus behavior, or the flush-on-unmount.
- Put `PendingEstimate` in `apps/web/core/` — it needs no store, and the package is the right home.
