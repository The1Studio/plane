# Phase 1 — `useWorkloadEstimateEditor` shared hook

**Plane:** [PLANE-81](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/782c853a-6aa0-40e2-a2a7-70c1693508e0) — 2h

**Effort:** M (2h) · **Depends on:** nothing · **Blocks:** phase 2

## Goal

One hook owning the entire "Estimated hours" edit lifecycle, so the three surfaces become
pure rendering. Behavior: commit 800 ms after the last keystroke, or immediately on Enter
(focus retained) or blur.

## Ownership

Creates exactly one file. Touches nothing else.

- `apps/web/core/hooks/store/use-workload-estimate-editor.ts` (NEW)

Placed beside the existing `use-workload-estimate.ts` for the same reason that file gives in
`docs/FORK.md`: a hook in `packages/workload-ext` is context-agnostic and cannot read core's
`useWorkload()`.

## Contract

```ts
export function useWorkloadEstimateEditor(args: {
  workspaceSlug: string | undefined;
  projectId: string | null | undefined;
  issueId: string;
}): {
  /** Controlled input value. Draft while focused, store value when idle. */
  value: string;
  /** Drives the "Saving…" label ONLY. Never wire this to `disabled`. */
  isSaving: boolean;
  onFocus: () => void;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onBlur: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
};
```

`value` is a **string**, not the `number | ""` peek/sidebar use today. A number-typed draft
cannot represent the intermediate `"12."` a user types on the way to `12.5`; the spreadsheet
cell already uses a string for this reason and is the shape to standardize on.

## Steps

1. **State.** `draft: string`, `isFocused: boolean`, `isSaving: boolean`. Read
   `{ hours, rollup }` from the existing `useWorkloadEstimate(issueId)` selector and the
   store from `useWorkload()`.

2. **Display.** `value = isFocused ? draft : hours !== null ? String(hours) : ""` — preserves
   today's behavior where a grid edit shows in the panel without reopening it.

3. **`commit(raw, { allowEmpty })`** — the single write path:
   - `raw.trim() === ""` and `!allowEmpty` → return (decision 4: never auto-save empty).
   - `parsed = raw.trim() === "" ? 0 : Number(raw)`; bail unless `Number.isFinite(parsed)`
     and `parsed >= 0`.
   - Dedup: bail if `parsed === (pendingValueRef.current ?? hours ?? 0)`. Set
     `pendingValueRef.current = parsed` **before** awaiting, so a blur firing right behind a
     debounce cannot re-send the same value while the first PUT is still open. Reset it to
     `null` on failure so a retry is allowed, and on focus.
   - Guard `!workspaceSlug || !projectId` → return.
   - `setIsSaving(true)`; `await store.updateEstimate(...)`; on
     `WorkloadEstimateApiError` with `errorCode === PARENT_HAS_CHILDREN_ERROR_CODE`, call
     `store.forceRefetchRollup(...)` and `setToast(...)` with the two existing
     `estimate.parent_has_children_toast_*` strings — this is a straight lift of the backstop
     already duplicated in all three files. `finally` → `setIsSaving(false)`.

4. **Serialize writes.** Chain through one ref so a second commit never overtakes the first:
   `inFlightRef.current = inFlightRef.current.then(() => doCommit(...)).catch(() => {})`.
   Without this, two debounced PUTs can resolve out of order and the store keeps the older
   value (`store.ts:updateEstimate` assigns `estimateData[issueId]` unconditionally on
   success; its `_writeEpoch` guard covers bulk GETs, not PUT-vs-PUT ordering).

5. **Debounce.** `useMemo(() => debounce((raw: string) => commitRef.current(raw, { allowEmpty: false }), 800), [])`
   from `lodash-es`, with `commitRef.current` kept pointed at the latest closure each render
   so the debounced call never fires against stale props. Same shape as
   `apps/web/core/hooks/use-auto-save.tsx`.

6. **Handlers.**
   - `onFocus` — seed `draft` from `hours`, set focused, clear `pendingValueRef`.
   - `onChange` — `setDraft(raw)` then `debounced(raw)`.
   - `onKeyDown` — on `Enter`: `e.preventDefault()`, `debounced.cancel()`,
     `commit(draft, { allowEmpty: true })`. **Do not blur** (decision 3).
   - `onBlur` — `debounced.cancel()`, clear focused, `commit(draft, { allowEmpty: true })`.

7. **Unmount.** `useEffect(() => () => debounced.flush(), [debounced])` — flush, not cancel,
   so an edit is not lost if the peek panel closes without a blur.

## Success criteria

- `pnpm --filter web typecheck` (or the repo's `pnpm check`) passes with the new file present.
- Reading the hook, each of these is traceable to a line: 800 ms idle commit · Enter commits
  and keeps focus · blur commits · empty never auto-commits but does commit as `0` on
  Enter/blur · a repeated value is not re-sent · two rapid saves cannot land out of order.
- `isSaving` is not referenced anywhere near a `disabled` computation.
