# Phase 2 — The input component and its place in the properties row

**Plan:** [plan.md](plan.md) · **Effort:** 3h · **Depends on:** [phase-1.md](phase-1.md) · **Blocks:** phase 3

## Goal

Render an "Estimated hours" control in the Add-work-item modal's bottom properties row, immediately
after the Due-date dropdown. One new fork-owned file, plus two small fenced edits.

## Ownership

```
apps/web/core/components/issues/issue-modal/components/estimated-hours-input.tsx  (NEW)
apps/web/core/components/issues/issue-modal/components/default-properties.tsx     (FENCED EDIT)
apps/web/core/components/issues/issue-modal/components/index.ts                   (FENCED EDIT)
```

Do not touch `form.tsx`, `base.tsx`, or any layout file in this phase.

## Steps

### 1. `estimated-hours-input.tsx` (NEW)

Fork-owned file. Header comment in the same shape as
`issue-layouts/spreadsheet/columns/estimated-hours-column.tsx`: copyright block, then
`The1Studio fork (SP2 workload) — documented core-edit exception. Listed in docs/FORK.md "Frontend
core-edit exceptions".`, then what it does and why it is two components.

Export one entry point:

```tsx
type TIssueEstimatedHoursInputProps = {
  /** Work item id — undefined in create mode. */
  issueId: string | undefined;
  projectId: string | null;
  workspaceSlug: string;
  /** True when the modal is in draft mode; the whole control is hidden. */
  isDraft: boolean;
  tabIndex?: number;
};

export const IssueEstimatedHoursInput = observer(function IssueEstimatedHoursInput(props) {
  if (props.isDraft || !props.projectId) return null;               // D5
  return props.issueId
    ? <UpdateModeInput ... issueId={props.issueId} />               // D1
    : <CreateModeInput ... />;                                      // D2
});
```

The early return sits **above** both branches so neither hook set is ever called conditionally;
each sibling calls its own hooks unconditionally.

**`CreateModeInput`** — no network at all:

- `const { pendingHours, setPendingHours } = usePendingEstimate();`
- A controlled `<input type="text" inputMode="decimal">` bound to `pendingHours`.
- `onChange` writes straight through to `setPendingHours(e.target.value)` — no debounce, no parse,
  no commit. Parsing happens once, in phase 3, at write time.
- No `isSaving` label; there is nothing being saved.

**`UpdateModeInput`** — live-commit, mirroring `EstimatedHoursBodyCell`:

- `const { rollup } = useWorkloadEstimate(issueId);`
- `const estimate = useWorkloadEstimateEditor({ workspaceSlug, projectId, issueId });`
- A ref-guarded `useEffect` calling `workloadStore.fetchEstimate(workspaceSlug, projectId, issueId)`
  inside a `try {} catch {}`, transcribed from `issue-detail/sidebar.tsx:102-112`. This is required,
  not optional: `useWorkloadEstimate` is a pure selector and the modal may open from a surface that
  never warmed the store, which would render an empty field for an item that has hours. The single
  GET populates `estimateData` **and** `rollupData`, so it also feeds the parent check below.
- **`rollup !== null` → read-only** (D10): render `formatRollupHours(rollup)` with
  `formatRollupTooltip(rollup)` as the title, exactly as the spreadsheet cell does. No input.
- Otherwise the input wires `value` / `onFocus` / `onChange` / `onBlur` / `onKeyDown` from the hook,
  and renders `wlt("common.saving")` beside it while `estimate.isSaving`.
- **`estimate.isSaving` must NOT reach the input's `disabled` attribute.** Saves fire mid-typing;
  disabling drops DOM focus and swallows the next keystrokes. The existing call sites carry this
  warning as an inline comment — carry it here too.

**Shared shell.** Both branches render inside the same wrapper so they are visually one control and
sit flush with the neighbouring dropdowns:

- Outer `<div className="h-7">`, matching every sibling `Controller` in the row.
- Inside, a bordered pill styled like `buttonVariant="border-with-text"`: rounded border, small
  horizontal padding, a clock icon, the `wlt("estimate.label")` affordance as the input's
  `placeholder` (`wlt("estimate.placeholder")` — "Hours") rather than a visible label, since every
  neighbour is icon-plus-value.
- Fixed narrow width (a `w-20`-class) so a long number does not reflow the row.

### 2. `default-properties.tsx` (FENCED EDIT)

Insert **between** the `target_date` `Controller` (currently ending ~line 203) and the cycle
`Controller` block — D3. The insertion is not wrapped in a `Controller`: this value is not part of
the react-hook-form `TIssue` schema and must not be added to it (`TIssue` is a `@plane/types` shape
the fork does not edit).

```tsx
{
  /* The1Studio fork (SP2 workload) — "Estimated hours" input, placed after the
    date dropdowns to mirror issue-detail/sidebar.tsx. Not a react-hook-form
    Controller: hours live in WorkloadEstimate, not on TIssue. */
}
<IssueEstimatedHoursInput
  issueId={id}
  projectId={projectId}
  workspaceSlug={workspaceSlug}
  isDraft={isDraft}
  tabIndex={getIndex("estimate_point")}
/>;
```

`id` and `isDraft` are already props on `TIssueDefaultPropertiesProps` — **no signature change**.

On `tabIndex`: `getTabIndex(ETabIndices.ISSUE_FORM)` reads a sealed key list in `@plane/constants`,
so there is no `estimated_hours` key to add without editing a sealed package. Reusing
`estimate_point`'s index keeps the field inside the form's tab cycle. If that produces a visibly
wrong tab order in manual check 4 below, drop the prop and let the element take natural DOM order
— **do not** add a key to `@plane/constants`.

### 3. `components/index.ts` (FENCED EDIT)

One fenced line:

```ts
// The1Studio fork (SP2 workload) — Estimated-hours input for the work-item modal.
export * from "./estimated-hours-input";
```

## Success criteria

- `pnpm check` clean; `pnpm turbo run build --filter=web` succeeds.
- Open the Add-work-item modal on a project: an hours pill sits between Due date and Cycle,
  visually level with its neighbours, and the row still wraps correctly at a narrow viewport.
- Typing in create mode changes nothing on the network — confirm zero requests to
  `workload-estimate` in the devtools Network tab while typing.
- Open an existing item with hours in the modal: the field is **pre-filled**. Open one from a
  freshly reloaded page that never rendered a spreadsheet — still pre-filled (this is the check
  that proves the fetch effect is doing its job, and the one that fails if it is dropped).
- Open a **parent** item: read-only Σ rollup, no input, tooltip matches the spreadsheet cell's.
- Open the modal in draft mode: no control rendered at all.
- Update mode: type a value, wait ~1s without touching Save — the spreadsheet behind the modal
  shows the new hours.

## Do not

- Add the field to `TIssue`, `DEFAULT_WORK_ITEM_FORM_VALUES`, or any `@plane/types` /
  `@plane/constants` file.
- Wire `isSaving` to `disabled`.
- Add an `estimated_hours` key to `ETabIndices`.
- Perform any create-mode network call — that is phase 3's job and belongs in `base.tsx`, where the
  created work item's id exists.
