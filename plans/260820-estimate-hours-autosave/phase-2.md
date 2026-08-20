# Phase 2 — Rewire the three surfaces

**Plane:** [PLANE-82](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/00c3e256-7235-44da-bc4f-f75e652bb16d) — 1.5h

**Effort:** S (1.5h) · **Depends on:** phase 1 (imports the hook) · **Blocks:** phase 3

## Goal

Delete the three duplicated copies of the edit state machine and drive every input from
`useWorkloadEstimateEditor`. Rendering, styling, and the rollup read-only branch are
unchanged.

## Ownership

- `apps/web/core/components/issues/issue-layouts/spreadsheet/columns/estimated-hours-column.tsx`
- `apps/web/core/components/issues/peek-overview/properties.tsx`
- `apps/web/core/components/issues/issue-detail/sidebar.tsx`

All three are existing `docs/FORK.md` core-edit exceptions. Keep every change inside the
existing `The1Studio fork (SP2 workload)` fences — this phase must not create a new fence
site, or it widens the rebase conflict surface for no gain.

## Steps

Per file, the same three edits:

1. **Delete** the local `estimateDraft` / `estimateFocused` / `estimateSaving` state, the
   `handleEstimateFocus` / `handleEstimateChange` / `handleEstimateBlur` trio, the
   `estimatedHoursValue` expression, and the now-unused `WorkloadEstimateApiError` /
   `PARENT_HAS_CHILDREN_ERROR_CODE` / `setToast` / `TOAST_TYPE` imports that only the
   backstop used. Keep `formatRollupHours` / `formatRollupTooltip` / `wlt` — the read-only
   rollup branch still needs them.

   Keep the `useEffect` + `estimateFetchedRef` single-issue `fetchEstimate` warm-up in
   `properties.tsx` and `sidebar.tsx` as-is. It is a read-path concern, not part of the edit
   lifecycle, and the spreadsheet cell deliberately has no equivalent (it is warmed in bulk
   by `useBulkWorkloadFetch`).

2. **Call the hook** and spread its handlers onto the `<input>`:

   ```tsx
   const estimate = useWorkloadEstimateEditor({ workspaceSlug, projectId, issueId });
   …
   <input
     type="number" min={0} max={10000} step={0.5}
     value={estimate.value}
     onFocus={estimate.onFocus}
     onChange={estimate.onChange}
     onBlur={estimate.onBlur}
     onKeyDown={estimate.onKeyDown}
     disabled={/* see step 3 */}
     …
   />
   {estimate.isSaving && <span …>{wlt("common.saving")}</span>}
   ```

   `workspaceSlug` / `projectId` arrive as `string | string[]` in the panels — pass
   `.toString()` exactly where the current code already does.

3. **Drop `saving` from every `disabled` gate.** This is the phase's load-bearing edit:

   | File                         | Before                                                      | After                                           |
   | ---------------------------- | ----------------------------------------------------------- | ----------------------------------------------- |
   | `estimated-hours-column.tsx` | `disabled={disableUserActions \|\| saving \|\| !projectId}` | `disabled={disableUserActions \|\| !projectId}` |
   | `properties.tsx`             | `disabled={disabled \|\| estimateSaving}`                   | `disabled={disabled}`                           |
   | `sidebar.tsx`                | `disabled={!isEditable \|\| estimateSaving}`                | `disabled={!isEditable}`                        |

   Under blur-only saving, disabling was harmless — the field was already unfocused. Under
   debounce saving it disables the input _mid-keystroke_, dropping DOM focus and swallowing
   what the user types next. Leave a one-line comment at each site saying so, or the next
   reader will "restore" it.

## Success criteria

- `grep -n "estimateSaving\|handleEstimateBlur\|estimatedHoursValue" apps/web/core/components/issues/` returns nothing.
- Typecheck + lint clean; no unused-import warnings from the deleted backstop imports.
- Manual smoke on each of the three surfaces: type `7` → pause → "Saving…" appears and the
  value survives a reload; type `8` → Enter → saves and the cursor is **still in the field**;
  type `9` → click away → saves; clear the field → wait 2 s → **no** request; then blur →
  commits `0`; a parent (rollup) issue still renders the read-only span with no input.
- Spreadsheet only: edit a cell, then confirm the peek panel for the same issue shows the new
  value without a reload (the shared-store read path must be unbroken).
