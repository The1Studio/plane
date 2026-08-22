# Phase 2 — `packages/cascade-ext`: store, modal, preview client

**Plane:** PLANE-111 · **Effort:** M (3.5h) · **Depends on:** Phase 1's endpoint contract · **Blocks:** Phase 3

## Goal

A self-contained fork package holding every line of cascade UI logic, so Phase 3's core edits are a
provider mount and two guard calls. Nothing here imports from `apps/web/core` — the dependency runs
one way.

## Ownership

```
packages/cascade-ext/**          # NEW package, exclusively this phase
apps/web/package.json            # touch-point 6, one workspace:* dep
```

Shape mirrors `packages/views-ext/` — the closest precedent in the fork.

## Exports

**`shouldPromptCascade(args)` — the guard that keeps the common case free.**

```ts
shouldPromptCascade(args: {
  data: Partial<TIssue>;
  subIssuesCount: number;
  getStateGroupById: (id: string) => string | undefined;
}): "completed" | "cancelled" | null
```

Returns the target group only when `data.state_id` is present **and** its group is terminal **and**
`subIssuesCount > 0`. Otherwise `null` — no preview request, no modal. Read the group via the state
store; never compare state **names** (Decision 7 — they are renameable, and #54 calls this out as
the thing that breaks the feature in every project that renamed a state).

This runs before any network call. A Done click on a leaf — the overwhelmingly common case — must
cost exactly zero extra requests.

**`cascadeService`** — `getPreview(...)` and `apply(...)` against the Phase 1 contract.

**`CascadeConfirmStore`** — a mobx store holding the pending request and a promise resolver:

```ts
requestCascade(params): Promise<{ cascade: false } | { cascade: true; childIds: string[] }>
```

Opens the modal, resolves when the user picks. Phase 3's store code awaits this and branches; it
holds no UI logic itself.

**`CascadeConfirmModal`** — built on `packages/ui`'s `modal-core.tsx`. Do not hand-roll a dialog;
that primitive already carries the fork's focus-trap and overlay behavior.

## Modal requirements (from #54, all blocking)

1. **Per-descendant rows**: identifier, name, current state name — not just a count. `#54` is
   explicit that a bare number is insufficient.
2. **A checkbox per row**, ticked by default for eligible rows.
3. **Ineligible rows shown disabled with their reason** ("no matching state in project X", "you do
   not have access to project X") — Decision 8. Not hidden, not silently dropped.
4. **Two buttons.** `Only change this item` holds **initial focus**; `Change sub-items too` does
   not. This is Decision 2 and the single most load-bearing detail in the whole modal — Enter must
   never cascade. Write a test that asserts focus, not just that both buttons render.
5. **Nesting is visible** — indent by `depth`, or label it. Full recursion ships in v1, so the "if
   only one level, say so in the modal" clause in #54 does not apply.
6. The modal is never opened with an empty eligible set (Decision 3); Phase 3 checks the preview
   before calling `requestCascade`.

## Strings

English literals live in this package (Decision 12). Do **not** add keys to `packages/i18n` — it is
a `@plane/*` package and the fork rules forbid editing those in place, so keys added there are lost
on the next upstream bump. If localisation is wanted later it gets its own decision.

## Tests

| Case | Assert |
| --- | --- |
| `shouldPromptCascade` — `state_id` absent | `null` |
| group `started` | `null` |
| `subIssuesCount === 0` | `null` |
| terminal + children | `"completed"` / `"cancelled"` respectively |
| state renamed `Done` → `Shipped` | still `"completed"` — resolved by group |
| modal focus | `Only change this item` has focus on open |
| **Enter immediately on open** | resolves `{ cascade: false }` |
| untick a row → confirm | that id absent from `childIds` |
| ineligible row | rendered, disabled, reason visible, never in `childIds` |
| all rows unticked → confirm | resolves `{ cascade: true, childIds: [] }`; Phase 3 treats this as a plain PATCH |

## Success criteria

- [ ] `pnpm check` clean.
- [ ] Package unit tests green, including the focus and Enter cases.
- [ ] `grep -rn "apps/web" packages/cascade-ext/src` → no hits (one-way dependency).
- [ ] `grep -rn "cascade" packages/i18n/src` → no hits (Decision 12).
- [ ] No state compared by name anywhere in the package — grep for `"Done"` / `"In Progress"` returns nothing outside test fixtures.
