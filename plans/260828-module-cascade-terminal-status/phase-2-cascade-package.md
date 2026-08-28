# Phase 2 — `packages/cascade-ext`: module client, guard, and the shared modal's summary mode

**Effort:** M (3h) · **Depends on:** Phase 1's frozen endpoint contract (not on Phase 1 merging)
**Blocks:** Phase 3
**Plan:** `plans/260828-module-cascade-terminal-status/plan.md`
**Plane:** [PLANE-192](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/a3af24bb-944f-4bae-8a9a-39960783b12f)

## Goal

Everything the module cascade needs on the client, inside the fork-owned package — so Phase 3's
core edit is a handful of lines rather than a feature.

## Ownership

```
packages/cascade-ext/src/types.ts                       # extend
packages/cascade-ext/src/strings.ts                     # extend
packages/cascade-ext/src/cascade-service.ts             # extend
packages/cascade-ext/src/should-prompt-cascade.ts       # extend
packages/cascade-ext/src/cascade-confirm-store.ts       # extend
packages/cascade-ext/src/cascade-confirm-modal.tsx      # extend
packages/cascade-ext/src/index.ts                       # re-export
packages/cascade-ext/src/__tests__/**                   # extend + new
```

Nothing outside `packages/cascade-ext/`. No `@plane/i18n` edit (M15) — strings stay local.

## Integration contract

The Phase 1 § "Endpoint contract" block is the contract. Copy it verbatim into this phase's working
notes; do not paraphrase field names or casing. The two paths, restated for the fetch client:

```
GET  /api/cascade-ext/workspaces/{slug}/projects/{projectId}/modules/{moduleId}/cascade-preview/?status={completed|cancelled}
POST /api/cascade-ext/workspaces/{slug}/projects/{projectId}/modules/{moduleId}/cascade-apply/
     body: { status, item_ids }
```

**TRAP, inherited from `cascade-service.ts`:** cascade-ext mounts at `/api/cascade-ext/`, outside
`/api/v1`. The existing service already handles this; reuse its base-URL derivation rather than
composing a new one.

## Implementation

### 1. `types.ts`

```ts
export type TModuleCascadeStatus = "completed" | "cancelled";

export type TCascadeItem = TCascadeDescendant & {
  is_module_member: boolean;
};

export type TModuleCascadeSummary = {
  total_live: number;
  eligible: number;
  ineligible: number;
  already_terminal: number;
};

export type TModuleCascadePreviewResponse = {
  target_group: TCascadeStateGroup;
  depth_capped: boolean;
  over_cap: boolean;
  cap: number;
  summary: TModuleCascadeSummary;
  items: TCascadeItem[];
};

export type TModuleCascadeApplyResponse = {
  module: string;
  status: TModuleCascadeStatus;
  updated: string[];
  rejected: TCascadeApplyRejection[];
};
```

`TCascadeApplyRejection["reason"]` widens to include
`"already_terminal" | "under_terminal_ancestor" | "not_in_module_tree"`. The first two also reach the
issue flow as of Phase 0, so widen the shared type rather than forking a module-only one.

### 2. `should-prompt-cascade.ts` — add the module guard

```ts
export const shouldPromptModuleCascade = ({
  data,
  totalIssues,
}: {
  data: Partial<IModule>;
  totalIssues: number;
}): TModuleCascadeStatus | null =>
  data.status === "completed" || data.status === "cancelled" ? (totalIssues > 0 ? data.status : null) : null;
```

Two properties this must hold, both tested:

- A payload that does **not** carry `status` returns `null` — that is what keeps a name-only edit
  on an already-completed module from firing a preview request (plan risk row).
- The guard deliberately does **not** subtract `completed_issues`/`cancelled_issues` from
  `total_issues`. Those counts cover direct members only, so the arithmetic does not describe the
  set the server will actually walk. See decision M6 — this is the cheaper guard's correctness hole,
  not an oversight. Put that reasoning in a comment on the function; the next reader will otherwise
  "optimize" it back. (Under M8's pruning a module whose members are all terminal now genuinely has
  nothing to cascade — but the guard must not encode that, because the server owns the rule and a
  client-side copy of it is the next thing to drift.)

### 3. `cascade-service.ts` — two methods

`getModulePreview(workspaceSlug, projectId, moduleId, status)` and
`applyModuleCascade(workspaceSlug, projectId, moduleId, status, itemIds)`. Same auth, same
`CascadeApiError` on non-2xx, same base-URL handling as the issue methods. The apply method sends
`item_ids` as an explicit array; it never omits the key (omission means "all", which the UI must
never request implicitly).

### 4. `cascade-confirm-store.ts` — one request shape, two sources

Widen `pendingRequest` rather than adding a second store: the modal is one component and two
stores would need two mount points in `root.tsx`.

```ts
type TCascadeSubject =
  | { kind: "issue"; parentIdentifier: string }
  | { kind: "module"; moduleName: string; summary: TModuleCascadeSummary; overCap: boolean; cap: number };
```

`requestModuleCascade({ moduleName, targetGroup, items, summary, overCap, cap })` returns the same
`Promise<TCascadeConfirmResult>` (`{ cascade: boolean; childIds: string[] }`) so Phase 3's call site
matches the shipped issue one.

When `overCap` is true the store pre-sets `checkedIds` to empty and the modal renders refusal mode
(below); resolving that promise always yields `{ cascade: false, childIds: [] }`.

The `cascadeConfirmStore` singleton stays exported **from this package**. Do not move it into a
store file — the existing header comment in `base-issues.store.ts` records that creating it there
closed an import cycle and crashed the SSR prerender with _"Cannot access 'BaseIssuesStore' before
initialization"_.

### 5. `cascade-confirm-modal.tsx` — summary header + collapsible list

One component, three additions:

- **Summary header**, always rendered. Issue subject: the existing sentence. Module subject: the
  counts — _"47 work items will be completed · 12 already done · 3 you cannot change."_ Zero-valued
  clauses are omitted, not rendered as "0". "Already done" counts terminal items the walk reached;
  it is not a total of everything skipped, because items behind a pruned branch are never visited
  (M8). Do not word the string as if it were a total.
- **Collapsible list.** `LIST_COLLAPSE_THRESHOLD = 15`. At or below the threshold the list renders
  expanded exactly as today, so the shipped issue flow is visually unchanged in every realistic
  case. Above it, the list starts collapsed behind a _"Show all 47 items"_ disclosure, with
  select-all / select-none above it.
- **Refusal mode** (`overCap`). No list, no checkboxes, no "Change work items too" button. Body:
  _"This module has 240 work items — more than the 100 this action can change at once. The module's
  status will still change."_ Single button: **"Only change this module."**

Unchanged and load-bearing: the `setTimeout` focus on **"Only change this item / module"**, so a
stray Enter never cascades.

### 6. `index.ts`

Re-export `shouldPromptModuleCascade`, the module service methods, the new types, and the widened
store API.

## Tests

| File                                       | Cases                                                                                                                                                                                                                                                                                  |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__tests__/should-prompt-cascade.test.ts`  | module guard: `completed`+`total_issues>0` → `"completed"` · `cancelled` → `"cancelled"` · `in-progress` → null · `total_issues===0` → null · **payload without `status`** → null · payload with `status` unchanged from current but present → still fires (the server decides no-ops) |
| `__tests__/cascade-confirm-store.test.ts`  | `requestModuleCascade` resolves on confirm and on dismiss · over-cap request resolves `{cascade:false, childIds:[]}` · select-all / select-none · the issue-path tests pass **unedited**                                                                                               |
| `__tests__/cascade-confirm-modal.test.tsx` | 3 items → list expanded, no disclosure · 40 items → collapsed, disclosure shows the count, expands on click · over-cap → no cascade button, cap and total both rendered · focus lands on the "only change" button in every mode · zero-valued summary clauses absent                   |
| `__tests__/cascade-service.test.ts` (new)  | module preview/apply hit the `/api/cascade-ext/…/modules/…` paths, not `/api/v1/…` · non-2xx raises `CascadeApiError` · apply always sends `item_ids` as an array                                                                                                                      |

## Success criteria

- `pnpm --filter @plane/cascade-ext test` green, with the **pre-existing** issue-path tests
  unedited.
- `pnpm check` clean.
- `git diff --name-only` touches only `packages/cascade-ext/`.
- Rendering an issue cascade with ≤15 descendants is visually identical to the shipped modal.
