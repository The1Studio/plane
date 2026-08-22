# Phase 3 — Fenced interception at the two store choke points

**Plane:** PLANE-112 · **Effort:** M (2.5h) · **Depends on:** Phases 1, 2

## Goal

All three entry points #54 requires — detail dropdown, list/spreadsheet dropdown, kanban
drag-and-drop — routed through the modal, via the fewest core edits that can cover them.

## Why two files cover three entry points

Both list/spreadsheet dropdowns and the kanban drop funnel into
`helpers/base-issues.store.ts` `updateIssue` (kanban goes `issue-layouts/utils.tsx:513`
`handleDragDrop` → `updateIssueOnDrop` → the store). The detail/peek dropdown goes through
`issue-details/issue.store.ts:181` `updateIssue`. Intercepting at the store is what makes three
surfaces cost two edits instead of three-plus — the same argument that made a backend hook
attractive, applied one layer up.

## Ownership

```
apps/web/core/store/issue/issue-details/issue.store.ts      # fenced block ONLY
apps/web/core/store/issue/helpers/base-issues.store.ts      # fenced block ONLY
apps/web/app/root.tsx                                       # touch-point 7, modal mount
docs/FORK.md                                                # new core-edit exception table
```

Fence string, both store files: `The1Studio fork (cascade-confirm)`. Change nothing else in them —
no reformatting, no touching neighbouring methods.

## The interception

Identical shape in both stores, at the top of `updateIssue`:

```ts
// The1Studio fork (cascade-confirm)
const targetGroup = shouldPromptCascade({ data, subIssuesCount, getStateGroupById });
if (targetGroup) {
  const preview = await cascadeService.getPreview({ ..., group: targetGroup });
  const eligible = preview.descendants.filter((d) => d.eligible);
  if (eligible.length > 0) {
    const choice = await cascadeConfirmStore.requestCascade({ preview, targetGroup });
    if (choice.cascade && choice.childIds.length > 0) {
      await cascadeService.apply({ ..., stateId: data.state_id, childIds: choice.childIds });
      return;   // apply() owns the parent write — do NOT fall through to the plain PATCH
    }
  }
}
// end The1Studio fork (cascade-confirm)
```

Three things this shape gets right, each of which is a bug if you change it:

- **`eligible.length > 0` before opening** — Decision 3. A preview whose rows are all ineligible
  must not raise a modal offering nothing.
- **The early `return` after `apply`** — the apply endpoint writes the parent inside its
  transaction. Falling through would PATCH the parent a second time, outside it.
- **Everything else falls through unchanged** — no `state_id`, non-terminal state, leaf, empty
  preview, "only this item", or zero ticked children all reach the original code path untouched.

`getStateGroupById` comes from the project-state store already reachable from both stores; resolve
it there rather than threading a new argument down.

## Modal mount

`apps/web/app/root.tsx:135` renders `<AppProvider>`. Mount `<CascadeConfirmModal />` inside it, in
its own fence. `root.tsx` is a **touch-point 7** path, so `plane-classify-path.cjs` classifies it as
a touch-point rather than an unregistered core edit — but the touch-point's documented purpose is
white-label branding, so note the widened use in `docs/FORK.md` rather than leaving a future reader
to wonder.

## `docs/FORK.md` registration — not optional

Add a section following the pattern at `docs/FORK.md:360-405`:

```
### Cascade-confirm modal for sub-work items — fenced `The1Studio fork (cascade-confirm)`
```

One row per file (both stores + `root.tsx`), with the "why no seam" column: upstream exposes no
pre-update hook on either store, and no global modal-host seam exists for a fork-owned dialog. Then
the standard closing paragraph:

> **Rebase handling:** these files ARE expected conflict points (unlike the abort-on-conflict rule
> for everything else). On conflict, re-apply the fork block — each is fenced by a
> `The1Studio fork (cascade-confirm)` comment — and keep upstream's changes around it. Do NOT abort
> the rebase for a conflict confined to this set.

Omitting this paragraph is what makes the next rebase abort.

## Success criteria

- [ ] `pnpm check` clean.
- [ ] Both store diffs are ≤ 18 added lines, entirely inside fences — verify with `git diff -U0`.
- [ ] `docs/FORK.md` names all three files with the fence string and carries the rebase paragraph.
- [ ] Manual, **all three entry points** (#54 requires each): detail dropdown, spreadsheet/list
      dropdown, kanban drag-drop → modal appears with the same rows.
- [ ] Manual: Done on a **leaf** → network tab shows the PATCH and **no** preview request.
- [ ] Manual: parent whose children are all already Done → no modal, no second request beyond preview.
- [ ] Manual: change a parent's **assignee** → no preview request.
- [ ] Manual: open the modal, press **Enter** immediately → only the parent changes.
- [ ] Manual: untick one child → it keeps its state; the others move.
- [ ] Manual: parent → **Cancelled** → children move to cancelled, an already-completed child is untouched.
