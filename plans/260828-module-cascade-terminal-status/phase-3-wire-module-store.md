# Phase 3 — Fence `module.store.ts` and register the exception

**Effort:** S (2h) · **Depends on:** Phases 1 and 2 (serial)
**Plan:** `plans/260828-module-cascade-terminal-status/plan.md`
**Plane:** [PLANE-193](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/d228efc0-e1c2-449e-8f53-c8937e6789c2)

## Goal

One fenced block at the single choke point every module status write funnels through, plus its
`docs/FORK.md` exception row. This is the only core file the feature touches.

## Ownership

```
apps/web/core/store/module.store.ts    # ONE fenced block + one fenced import — registered core exception
docs/FORK.md                           # exception row + cascade_ext entry update
```

`apps/web/app/root.tsx` needs **no** change: `<CascadeConfirmModal store={cascadeConfirmStore} />`
is already mounted there (touch-point 7, already registered), and Phase 2 reuses that same store
and component rather than adding a second host.

## Why this one file

Five UI entry points can change a module's status, and all five call the same store method:

| Entry point              | File:line                                                          |
| ------------------------ | ------------------------------------------------------------------ |
| Module list row          | `components/modules/module-list-item-action.tsx:112`               |
| Module grid card         | `components/modules/module-card-item.tsx:125`                      |
| Analytics sidebar (peek) | `components/modules/analytics-sidebar/root.tsx:82`                 |
| Create/update modal      | `components/modules/modal.tsx:82`                                  |
| Power-K palette          | `components/power-k/ui/pages/context-based/module/commands.tsx:45` |

All five reach `updateModuleDetails` — `apps/web/core/store/module.store.ts:431`. The gantt layout
(`gantt-chart/modules-list-layout.tsx:38,51`) also calls it, but only ever with
`sort_order` / `start_date` / `target_date`, so the `data.status` guard makes it a no-op there for
free. `SidebarStatusSelect` (`sidebar-select/select-status.tsx:28`) is exported but has no callers —
do not add a fence for it.

`apps/space` has no module write path at all. Nothing to guard.

## Implementation

Guard at the **top** of `updateModuleDetails`, before the optimistic `set` — a module the user
declines to cascade still gets its status written by the plain PATCH below, so the optimistic write
is correct either way, but the preview must not race it.

```ts
// The1Studio fork (module-cascade) — see docs/FORK.md § "Cascade a module's terminal status".
// Every module status write funnels through this method (list row, grid card, analytics sidebar,
// create/update modal, power-K), so one guard here covers all five with no duplicate fence.
const cascadeModule = this.getModuleById(moduleId);
const cascadeStatus = shouldPromptModuleCascade({
  data,
  totalIssues: cascadeModule?.total_issues ?? 0,
});
if (cascadeStatus) {
  const preview = await cascadeService.getModulePreview(workspaceSlug, projectId, moduleId, cascadeStatus);
  const eligible = preview.items.filter((i) => i.eligible);
  if (preview.over_cap || eligible.length > 0) {
    const choice = await cascadeConfirmStore.requestModuleCascade({
      moduleName: cascadeModule?.name ?? moduleId,
      targetGroup: preview.target_group,
      items: preview.items,
      summary: preview.summary,
      overCap: preview.over_cap,
      cap: preview.cap,
    });
    if (choice.cascade && choice.childIds.length > 0) {
      // applyModuleCascade writes the module's status INSIDE its own transaction — falling through
      // to the plain patchModule below would write it a second time, outside that transaction.
      await cascadeService.applyModuleCascade(workspaceSlug, projectId, moduleId, cascadeStatus, choice.childIds);
      // total_issues / completed_issues / cancelled_issues drive the progress ring rendered right
      // beside the status control, and the cascade moved them server-side.
      await this.fetchModuleDetails(workspaceSlug, projectId, moduleId);
      return;
    }
  }
}
// Every other case — no cascade status, an empty or all-ineligible preview, "only change this
// module", or zero ticked items — falls through unchanged to the optimistic set + patchModule below.
// end The1Studio fork (module-cascade)
```

Three things to get right, each a real failure if missed:

1. **`over_cap ||` in the modal condition.** Over cap, `items` is `[]` and `eligible.length` is
   zero — an `eligible.length > 0`-only condition would skip the refusal modal entirely and silently
   complete a 600-item module's status with no explanation of why nothing cascaded.
2. **The early `return` after apply.** Falling through would PATCH the module a second time, outside
   the transaction. The shipped issue fence carries the same comment for the same reason.
3. **Preview failures must not block the status change.** Wrap the preview call so a 4xx/5xx from
   `cascade-ext` (an older server, a deploy skew) logs and falls through to the plain PATCH. A fork
   add-on being unreachable must never break a core action.

Confirm the exact `fetchModuleDetails` method name against the store before writing the call —
`module.store.ts` also exposes `fetchModules`; the per-module refetch is the cheaper one.

## `docs/FORK.md`

1. Add a row to the exception table in the cascade block:

   | File                                  | What                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Why no seam                                                                                                                              |
   | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
   | `apps/web/core/store/module.store.ts` | At the top of `updateModuleDetails` — `shouldPromptModuleCascade` guard → `cascadeService.getModulePreview` → (if any row is eligible, or the preview is over cap) `cascadeConfirmStore.requestModuleCascade` → on a cascade choice with ticked items, `cascadeService.applyModuleCascade`, a `fetchModuleDetails` refetch, and an early `return` so the plain `patchModule` below never double-writes the module. Every other case falls through unchanged. | No upstream pre-update hook on the module store, and `updateModuleDetails` is the one method all five status entry points funnel through |

2. Extend the existing `cascade_ext` entry to say the app now serves **two** subjects — issue trees
   and module contents — sharing one BFS/eligibility core, and note `MAX_MODULE_CASCADE_ITEMS = 100`
   as a refusal, not a truncation.

3. Add `apps/web/core/store/module.store.ts` to the block's "Rebase handling" note as an expected
   conflict point where the fork block is re-applied, not abandoned.

## Verification

- `pnpm check` clean.
- `node .claude/scripts/plane-classify-path.cjs` over the full diff — every path classifies `fork`
  or as a **registered** exception. Zero unregistered-core results.
- Manual, all five entry points: status → `completed` on a module with live work → modal opens ·
  "Only change this module" → module moves, no work item moves · "Change work items too" → both
  move **and the progress ring updates without a page reload** · status → `in-progress` → no
  preview request in the network tab · rename a completed module without touching status → no
  preview request · empty module → no modal · module whose items are all done → no modal ·
  240-item module → refusal modal, status still changes · `cascade-ext` returning 500 (block it in
  devtools) → status change still succeeds.

## Success criteria

- One fenced block and one fenced import in `module.store.ts`; nothing else in `apps/web/` touched.
- `docs/FORK.md` carries the exception row before the PR is opened, not after.
- The network tab shows **zero** extra requests for every non-terminal status change.
