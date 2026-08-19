# Phase 2 — Frontend: status filter as a dropdown

**Effort:** S (~3h) · **Depends on:** nothing · **Blocks:** nothing

## Goal

The toolbar renders Members, Projects and Status as three identical
`border-with-text` dropdowns. The inline state-group chip row is gone.

## Files owned

- `apps/web/core/components/workload/StateGroupDropdown.tsx` (new)
- `apps/web/core/components/workload/index.ts` (new barrel — `components/workload/`
  currently holds only `timeline/`, which owns its own `index.ts`; the page imports
  `@/components/workload/timeline`, so the new component is imported as
  `@/components/workload/StateGroupDropdown` and the barrel is optional. Add it only
  if you also re-export `timeline` from it.)
- `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx`
- `packages/workload-ext/src/WorkloadToolbar.tsx`

## Steps

1. **New component `StateGroupDropdown.tsx`.** Model it on
   `apps/web/core/components/dropdowns/project/base.tsx` — same imports and same
   composition, so an upstream restyle of the dropdown chrome propagates here:
   - `ComboDropDown` (`@plane/ui`) as the root, `multiple`, `value: string[]`,
     `onChange: (val: string[]) => void`.
   - `DropdownButton` (`@/components/dropdowns/buttons`) with
     `variant={buttonVariant}`, `isActive={isOpen}`, `tooltipHeading="Status"`.
   - `useDropdown` (`@/hooks/use-dropdown`) for `handleClose` / `handleKeyDown` /
     `handleOnClick` / `searchInputKeyDown`.
   - `usePopper` positioning, `Combobox.Options` panel with the same
     `w-48 rounded-sm border-[0.5px] …` shell.
   - Options come from `Object.values(STATE_GROUPS)` (`@plane/constants`), each
     rendering `<StateGroupIcon stateGroup={group.key} />` (`@plane/propel/icons`)
     - `group.label`; selected rows get the `CheckIcon` tick.

   Deliberate divergences from the project base, each worth a one-line comment:
   - **No search input.** Five fixed options; a search box over five rows is noise.
     (Drop `Combobox.Input`, `query` state, and `searchInputKeyDown` with it.)
   - **No `sortBySelectedFirst`.** With five non-scrolling rows, reordering on
     select makes the list jump under the cursor for no gain.
   - **Fixed vocabulary, no store hook.** `STATE_GROUPS` is a constant, so unlike
     `ProjectDropdown` this component needs no `observer` wrapper and no
     `useProject`-style hook — it is a controlled input, nothing more.

   Button label rule: `0` selected → the `placeholder`; `1` → that group's
   `label`; `n>1` → `${n} statuses`. Mirrors `getDisplayName` in the project base.

2. **`WorkloadToolbar` — add `stateFilterSlot`.** In
   `packages/workload-ext/src/WorkloadToolbar.tsx`:
   - Add `stateFilterSlot?: React.ReactNode` to `WorkloadToolbarProps`, documented
     the same way as the two existing slots (host-injected because the package
     cannot import `apps/web`).
   - Render it where the chip `<div role="group">` is today.
   - Delete `handleStateGroupToggle`, the `STATE_GROUP_KEYS` constant, the chip
     `<div>`, and the now-unused `STATE_GROUPS` import.
   - Keep `hasActiveFilters` and `handleClearFilters` exactly as they are — the
     clear button must still reset state groups (plan success criterion 5).
   - `filters.state_groups` ("Status") stays in `src/i18n.ts` and becomes the
     dropdown's placeholder, passed by the host.

3. **Wire the host.** In `workload/page.tsx`:
   - `const handleStateGroupChange = useCallback((keys: string[]) => workloadStore.setStateGroups(keys), [workloadStore])`
     — same shape as the existing `handleMemberChange` / `handleProjectChange`.
   - Pass `stateFilterSlot={<StateGroupDropdown multiple value={workloadStore.selectedStateGroups} onChange={handleStateGroupChange} buttonVariant="border-with-text" placeholder={wlt("filters.state_groups")} />}`.

## Verification

```bash
pnpm check
```

Then in the running app, at `/{workspaceSlug}/workload/`:

- open Status, tick two groups → the timeline refetches and the button reads `2 statuses`;
- untick both → the button reads `Status` and every state group is shown again
  (see memory `no-filter-means-no-filtering`: an empty selection means _no_
  filtering, never a hidden default exclusion — this is `store.setStateGroups([])`
  behaviour and must not regress);
- `Clear filters` resets all three dropdowns.

## Success criteria

- Zero `role="group"` chip row remains in `WorkloadToolbar`.
- The three dropdowns are visually indistinguishable in height, border, and type
  scale.
- `packages/workload-ext` still builds standalone: omitting `stateFilterSlot`
  renders nothing and throws nothing.
