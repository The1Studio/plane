# "Estimated hours" — save on stop-typing or Enter

**Created:** 2026-08-20
**Branch:** `feat/workload-estimate-autosave`
**Plane:** [PLANE-80](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/6292479d-790c-4e5d-8c1d-487058c369dc) — parent, Infrastructure › Plane, 4.5h rolled up
**Plane:** [PLANE-81](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/782c853a-6aa0-40e2-a2a7-70c1693508e0) — Phase 1, 2h
**Plane:** [PLANE-82](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/00c3e256-7235-44da-bc4f-f75e652bb16d) — Phase 2, 1.5h
**Plane:** [PLANE-83](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/244963da-b3dd-4a11-abe0-f1a579559348) — Phase 3, 1h
**Scope:** the three fork-owned "Estimated hours" input surfaces + one new shared hook. No API change.

## Problem

Every "Estimated hours" input in the fork commits **only on blur**. A user who types a
value and then clicks a chart, switches tabs, or hits Enter expecting a commit gets no
save and no feedback — the number simply reverts to the stored value on the next render.
Enter does nothing at all today: `<input type="number">` has no `onKeyDown` handler on any
of the three surfaces.

The requested behavior: commit when the user **stops typing** (800 ms idle) or presses
**Enter**, with blur retained as the final safety net.

## Prior art

`grep -rn "updateEstimate\|useWorkloadEstimate" apps/web --include=*.tsx --include=*.ts`
returns **exactly three** editable surfaces (plus read-only consumers). All three carry a
near-identical copy of the same state machine — `draft` / `focused` / `saving`, a
`handleEstimateFocus` seed, a passthrough `handleEstimateChange`, and a
`handleEstimateBlur` that PUTs and runs the `PARENT_HAS_CHILDREN` backstop:

| Surface                 | File                                                                                           | Lines   |
| ----------------------- | ---------------------------------------------------------------------------------------------- | ------- |
| Spreadsheet grid cell   | `apps/web/core/components/issues/issue-layouts/spreadsheet/columns/estimated-hours-column.tsx` | 77–131  |
| Peek / quick-view panel | `apps/web/core/components/issues/peek-overview/properties.tsx`                                 | 95–155  |
| Issue-detail sidebar    | `apps/web/core/components/issues/issue-detail/sidebar.tsx`                                     | 102–161 |

Read-only consumers — not touched: `progress-column.tsx`, `ce/.../additional-properties.tsx`,
`WorkloadTimelineChartBlock.tsx`.

Debounce helpers already in the repo (`zero across apps/web/core/hooks`, `packages/hooks/src`
searched): `apps/web/core/hooks/use-debounce.tsx` debounces a _value_, not a callback — wrong
shape here, since the commit must also be flushable on Enter/blur. `lodash-es`'s `debounce`
is already a direct dependency and is used this way in `apps/web/core/hooks/use-auto-save.tsx`
(`debounce()` + `.cancel()`); that is the precedent this plan follows.

No shared editor hook exists — `apps/web/core/hooks/store/use-workload-estimate.ts` holds only
the read-side selectors (`useWorkloadEstimate`, `useBulkWorkloadFetch`).

## Decisions (resolved)

| #   | Decision                                                                                                                                                                                |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | All three surfaces get the behavior, via one extracted hook.                                                                                                                            |
| 2   | Idle threshold is **800 ms**.                                                                                                                                                           |
| 3   | **Enter** flushes the pending save immediately and **keeps focus**.                                                                                                                     |
| 4   | An empty field is **never** auto-saved. Empty commits as `0` only on explicit Enter or blur — unifying today's split (spreadsheet saves `0` on blur; peek/sidebar skip empty entirely). |

## The load-bearing constraint

All three inputs currently render `disabled={… || saving}`. That is harmless when the only
save fires on blur — the field is already unfocused. Under debounce saving it is a defect:
the input is disabled _while the user is still typing in it_, which drops DOM focus and
silently swallows the next keystrokes. **`isSaving` must drive the "Saving…" label only,
never the `disabled` attribute.** Phase 2 removes it from all three disable gates.

## Phases

| Phase           | Goal                                                                                                                        | Effort   |
| --------------- | --------------------------------------------------------------------------------------------------------------------------- | -------- |
| [1](phase-1.md) | New shared hook `useWorkloadEstimateEditor` — debounce, Enter flush, blur flush, dedup, write serialization, error backstop | M (2h)   |
| [2](phase-2.md) | Rewire the three surfaces onto the hook; drop `saving` from every `disabled` gate                                           | S (1.5h) |
| [3](phase-3.md) | `docs/FORK.md` exception row, `CLAUDE.md` note, verification sweep                                                          | S (1h)   |

Sequential — phase 2 imports the hook phase 1 writes; phase 3 documents what 1+2 landed.
No fan-out, so no worktree allocation and no file→owner map is needed.

## Risk Assessment

| Risk                                                                            | L   | I   | Score | Mitigation                                                                                                  |
| ------------------------------------------------------------------------------- | --- | --- | ----- | ----------------------------------------------------------------------------------------------------------- |
| Disabled-while-saving drops focus mid-typing                                    | 5   | 4   | 20    | Phase 2 removes `saving` from all three `disabled` gates; called out as the plan's load-bearing constraint  |
| Two debounced PUTs race; the older response lands last and stores a stale value | 2   | 4   | 8     | Phase 1 chains every commit through one in-flight promise, so writes are strictly ordered per hook instance |
| Debounce fires a duplicate write that blur/Enter already sent                   | 3   | 2   | 6     | `.cancel()` before every explicit flush, plus a `pendingValueRef` dedup guard set _before_ the await        |
| Pending save lost when the peek panel unmounts                                  | 2   | 3   | 6     | Flush (not cancel) on unmount; blur normally fires first anyway                                             |
| Rebase conflict — all three files are known upstream conflict points            | 3   | 2   | 6     | Edits stay inside the existing `The1Studio fork (SP2 workload)` fences; no new fence sites                  |

No risk scores ≥ 15 remain unmitigated.

## Out of scope

- Any API, serializer, or model change. `PUT /workload/…/estimate/` is unchanged, so per
  `CLAUDE.md` § standing rule there is **nothing to propagate** to `plane-mcp-server`,
  the SDKs, or the plugin — this is a client-side commit-timing change only.
- The read-only rollup path (parent issues render a `<span>`, never an input).
- The `deleteEstimate` / ADMIN path — still deliberately unused; empty commits as `0`.

## Cook handoff

`/t1k:cook plans/260820-estimate-hours-autosave/`
