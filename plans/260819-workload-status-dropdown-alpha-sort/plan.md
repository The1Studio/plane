# Workload timeline — status filter as dropdown + alphabetical member order

**Created:** 2026-08-19
**Branch:** company-main
**Repo:** The1Studio/plane (fork) — Plane project `PLANE`

## Goal

Two independent changes to the workspace workload timeline (`/{workspaceSlug}/workload/`):

1. **Status filter → dropdown.** The five state-group chips (Backlog · Unstarted ·
   Started · Completed · Cancelled) currently render as inline toggle buttons in
   `WorkloadToolbar`, taking ~40% of the toolbar row. Replace them with a single
   multi-select dropdown visually and behaviourally identical to the existing
   Members and Projects dropdowns.
2. **Member swimlanes → alphabetical.** The API sorts rows busiest-first
   (`-total, assignee_name`). Sort by name instead (case-insensitive), with the
   `Unassigned` bucket pinned to the top.

## Decisions (resolved)

| #   | Decision                                                                                                                                                                                                                                                                                                                                                                                       |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | `Unassigned` is **pinned first**, ahead of the A→Z member run.                                                                                                                                                                                                                                                                                                                                 |
| D2  | The alphabetical sort is applied **server-side, replacing** the busiest-first order in `workload/service.py`. One SSOT ordering for every consumer (web timeline, MCP `get_workload`).                                                                                                                                                                                                         |
| D3  | The status dropdown is **app-injected** through a new `stateFilterSlot` prop, matching the existing `memberFilterSlot` / `projectFilterSlot` inversion. `packages/workload-ext` cannot import `apps/web` internals (`@/hooks/use-dropdown`, `@plane/ui` `ComboDropDown`, `../buttons`), so building it in the package would produce an approximation of the chrome rather than the real thing. |
| D4  | The new dropdown lives at `apps/web/core/components/workload/StateGroupDropdown.tsx`, alongside the already fork-owned `timeline/` directory (documented core-edit exception D13 in `docs/FORK.md`). No new touch-point, no new exception.                                                                                                                                                     |

## Prior art (searched before specifying new work)

| Concern                               | Existing code                                                                                                                                                                                                                                                                                    | Reused?                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------- | --------------- |
| State-group vocabulary                | `STATE_GROUPS` in `packages/constants/src/state.ts` (`{key, label, color}`)                                                                                                                                                                                                                      | Yes — already imported by `WorkloadToolbar` |
| State-group icon                      | `StateGroupIcon` from `@plane/propel/icons` — used by `issue-layouts/filters/header/filters/state-group.tsx`                                                                                                                                                                                     | Yes                                         |
| Multi-select dropdown chrome          | `apps/web/core/components/dropdowns/project/base.tsx` (headlessui `Combobox` + `react-popper` + `ComboDropDown` + `DropdownButton` + `useDropdown`)                                                                                                                                              | Yes — the new component is modelled on it   |
| A ready-made state-**group** dropdown | Zero across `apps/web/core/components/dropdowns/`, `packages/ui/src`, `packages/propel/src`. `dropdowns/state/` is per-project _states_, not groups; `issue-layouts/filters/header/filters/state-group.tsx` is a filter-panel section (`FilterHeader`/`FilterOption`), not a standalone dropdown | No — new component needed                   |
| Generic `CustomSearchSelect`          | Zero across `packages/ui/src/index.ts`, `packages/propel/src`                                                                                                                                                                                                                                    | No                                          |
| Row-order assertions in tests         | Zero across `apps/api/plane/workload/tests/*.py` (`grep 'rows.sort                                                                                                                                                                                                                               | assignee_name'`)                            | New test needed |
| MCP ordering contract                 | `~/Projects/plane-mcp-server/plane_mcp/tools/workload.py:107` documents the row **shape**, not its order                                                                                                                                                                                         | Docstring note only                         |

## Phases

| Phase           | Scope                                                                      | Effort    |
| --------------- | -------------------------------------------------------------------------- | --------- |
| [1](phase-1.md) | Backend — alphabetical row sort, `Unassigned` first, regression test       | S (~2h)   |
| [2](phase-2.md) | Frontend — `StateGroupDropdown` + `stateFilterSlot`, remove inline chips   | S (~3h)   |
| [3](phase-3.md) | Propagation — MCP docstring issue in `plane-mcp-server`, `CLAUDE.md` entry | S (~0.5h) |

Phases 1 and 2 touch disjoint files and have no dependency on each other; phase 3
follows phase 1. Single-agent execution — the fan-out would cost more than the
work.

## File ownership (zero overlap)

| Phase | Files                                                                                                                                                                                                                                               |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | `apps/api/plane/workload/service.py`, `apps/api/plane/workload/tests/test_task_rows.py`                                                                                                                                                             |
| 2     | `apps/web/core/components/workload/StateGroupDropdown.tsx` (new), `apps/web/core/components/workload/index.ts` (new, if absent), `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx`, `packages/workload-ext/src/WorkloadToolbar.tsx` |
| 3     | `CLAUDE.md`; an **issue** (not an edit) on `The1Studio/plane-mcp-server`                                                                                                                                                                            |

## Success criteria

1. `GET /api/workload/workspaces/<slug>/` returns `rows` with `assignee_id: null`
   first, then remaining rows ascending by `assignee_name` case-insensitively.
2. A member with the largest `total` no longer appears first purely because of
   their load.
3. The workload toolbar shows exactly three controls — Members, Projects, Status
   — all rendering the same border-with-text dropdown chrome.
4. Selecting/deselecting groups in the Status dropdown drives
   `store.selectedStateGroups` exactly as the chips did (same setter, same
   server-side refetch path), and the button label reads the group name for one
   selection, `N statuses` for several, and `Status` for none.
5. `Clear filters` still resets projects + assignees + state groups.
6. `python manage.py check`, `pnpm check`, and the workload pytest module all pass.

## Risk Assessment

| Risk                                                                                            | Likelihood | Impact | Score | Mitigation                                                                                                                                |
| ----------------------------------------------------------------------------------------------- | ---------- | ------ | ----- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Replacing the API sort surprises an MCP/API consumer relying on busiest-first                   | 2          | 3      | 6     | Phase 3 documents the change; no consumer currently asserts order (`grep` over `plane_mcp/tools/workload.py` found a shape contract only) |
| `blocks.ts` assumes server row order and its docstring says "sorted by `-total, assignee_name`" | 3          | 2      | 6     | The builder only _consumes_ order; phase 1 updates that docstring so the next reader is not misled                                        |
| New dropdown drifts from Plane's chrome after an upstream restyle                               | 2          | 2      | 4     | Component composes `DropdownButton` + `ComboDropDown` rather than re-implementing them, so an upstream restyle propagates                 |
| `sortBySelectedFirst` on a 5-item list makes the option order jump on selection                 | 2          | 1      | 2     | Omit it — five fixed groups fit without scrolling                                                                                         |

## Timeline

| Phase               | Effort    | Notes                |
| ------------------- | --------- | -------------------- |
| 1 — Backend sort    | S (~2h)   | No dependency        |
| 2 — Status dropdown | S (~3h)   | No dependency        |
| 3 — Propagation     | S (~0.5h) | After phase 1        |
| Total               | ~5.5h     | Critical path: 1 → 3 |
