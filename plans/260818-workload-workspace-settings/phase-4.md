# Phase 4 — Frontend: workspace settings page

**Goal:** an admin-only workspace settings page for the three values, plus removal of the
per-person capacity input and its store/service methods. Depends on Phase 1 (the API).

The workload **view** itself is [`phase-8.md`](phase-8.md) — this phase only strips the
per-member capacity grain out of the existing package; the timeline replaces the table there.

Parent plan: [`plan.md`](plan.md). Contract: [`phase-0.md`](phase-0.md).

## Ownership

- `apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/page.tsx` (new)
- `apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/header.tsx` (new)
- `apps/web/app/routes/extended.ts` (touch-point 6 — append only)
- `apps/web/core/components/settings/workspace/sidebar/item-categories.tsx` (core-edit exception)
- `apps/web/core/hooks/store/use-work-settings.ts` (new)
- `packages/workload-ext/src/**`

## Route mounting (touch-point 6, no `core.ts` edit)

`extendedRoutes` supports nested `layout()` chains — the existing workload page already proves it
(`extended.ts:19-25`). Mirror the settings chain from `core.ts:258-284`:

```ts
layout("./(all)/layout.tsx", [
  layout("./(all)/[workspaceSlug]/layout.tsx", [
    layout("./(all)/[workspaceSlug]/(settings)/layout.tsx", [
      layout("./(all)/[workspaceSlug]/(settings)/settings/(workspace)/layout.tsx", [
        route(":workspaceSlug/settings/workload",
          "./(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/page.tsx"),
      ]),
    ]),
  ]),
]),
```

Verify `mergeRoutes` deep-merges into the same shell rather than creating a second settings
layout instance — if the sidebar renders twice, the layout chain is wrong, not the route.

## Nav entry (core-edit exception)

`WORKSPACE_SETTINGS` lives in the sealed `@plane/constants` package
(`packages/constants/src/settings/workspace.ts:23`) and must not be edited in place. Append the
item in the **consuming** component instead — `item-categories.tsx`, inside the
`WORKSPACE_SETTINGS_CATEGORY.FEATURES` group, fenced with a
`/* The1Studio fork (workspace work settings) */` comment. This mirrors the existing
`sidebar-menu-items.tsx` exception already recorded in `docs/FORK.md`.

Access: `ADMIN` only — the page writes.

## `useWorkSettings()` hook

One hook is the single read path for all three values, consumed by this phase **and** Phase 5's
core-component edits. Putting the fetch anywhere else means Phase 5 has 8 divergent call sites.

- Fetches `GET /api/workspaces/<slug>/work-settings/`.
- Returns `TWorkSettings` (never `undefined` — falls back to the Phase 0 defaults while loading,
  so no consumer branches on absence).
- Exposes `updateWorkSettings(partial)` issuing the PUT; admin-gated at the call site, not here.

## Settings page

Three controls, one save action:

| Control | Widget | Validation (mirrors the serializer) |
|---|---|---|
| Max weekly hours | number input, `min=0`, `step=0.5` | `0 ≤ x ≤ 10000` |
| Workdays | 7 toggles (Sun…Sat, ordered by `week_start_day`) | at least one selected |
| First day of week | select of the 7 `EStartOfTheWeek` values | — |

Client validation exists to avoid a round-trip, not as the gate — the server is the gate. Disable
save while invalid; surface the server error verbatim on 400.

Non-admins never reach the page (nav item hidden + route guard), but the API GET is `MEMBER`-visible
so the matrix can still render correct columns for them.

## Capacity removal (`packages/workload-ext`)

1. **Delete `CapacityBadge`** (`WorkloadMatrix.tsx:26-88`) and its column — both the admin input
   and the read-only badge. Per-person capacity no longer exists (D1).
2. Delete `store.capacities`, `store.updateCapacity`, `fetchCapacities`, and the capacity
   service methods (`store.ts`, `service.ts`).
3. Add a read-only workspace readout to `WorkloadToolbar`:
   `Max <N>h/week · <workdays> · week starts <day>`, linking to the settings page for admins.
4. `i18n.ts` — remove `matrix.cap_short` / `matrix.capacity`; add the toolbar readout strings.

`WorkloadMatrix.tsx` is **not** deleted here — Phase 8 owns that, once the timeline replaces it.
Leaving the table working through this phase keeps every phase independently shippable.

## Tasks

1. `useWorkSettings()` hook + types wiring.
2. Settings page + header + route + nav entry.
3. Capacity removal (steps 1–2 above).
4. Toolbar settings readout (step 3).
5. i18n cleanup.

## Success criteria

- `pnpm check` clean.
- `/:workspaceSlug/settings/workload` renders inside the normal settings shell with a single
  sidebar, and the nav item appears for admins only.
- `grep -rn "capacities\|updateCapacity\|CapacityBadge" packages/workload-ext apps/web | grep -v node_modules`
  returns zero hits.
- Saving each of the three values round-trips and the matrix re-renders with the new bucketing.
