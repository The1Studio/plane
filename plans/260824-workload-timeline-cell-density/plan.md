# Workload timeline — per-zoom task-bar density

**Branch:** `feat/workload-timeline-cell-density` (off `company-main`)
**Total estimate:** 4.5h across 3 phases
**Scope:** frontend presentation only. No endpoint, no field, no serializer, no migration.

## What changes

The workload timeline's "cells" are the task bars inside each assignee swimlane
(`WorkloadTimelineChartBlock`, the `data.kind === "lane"` branch). Today a bar renders
`name · Nh` at Week and Month zoom, and `Nh` alone at Quarter, at a uniform 32px height with a
60px minimum width.

Three changes, one per zoom band:

| Zoom | Today | After |
|---|---|---|
| **Week** (`dayWidth` 180) | one line: name + hours, 32px tall | two lines: small `PROJ-142` identifier top-left, name + hours below; bar grows to 40px |
| **Month** (`dayWidth` 60) | one line: name + hours | hours only, centred — same treatment Quarter already gets |
| **Quarter** (`dayWidth` 30) | hours only, min width 60px | hours only, min width **30px** (true 1-day duration) with a font/padding ladder so the number stays whole |

## Resolved decisions

| # | Decision | Resolution |
|---|---|---|
| D1 | What "halve the cell size" means | `MIN_BAR_WIDTH` 60 → 30. It binds **only at Quarter** — at Month a 1-day bar is already `dayWidth` = 60px and at Week 180px, so neither is touched by the floor today or after. |
| D2 | Does Month lose the task name | Yes. Month and Quarter both render the estimate alone, centred. The name survives in the hover `title` and is unaffected at Week. |
| D3 | Week identifier placement | Top-left corner, smaller font, name + hours on the line below. |
| D4 | Week bar height | 40px (`h-10`) inside the unchanged 44px `BLOCK_HEIGHT` lane row. Month/Quarter bars stay 32px. |
| D5 | What a bar does when the estimate will not fit | A three-step ladder: render at `text-11`/`px-2`; if that overflows, retry at `text-9`/`px-0.5`; if that still overflows, **drop the label** and keep the tooltip. Never clip. |

D5 preserves the rule already written into this file's `MIN_BAR_WIDTH` docstring — *a missing
label is recoverable, a truncated one is a lie*. With `justify-center` a clipped `10.75h` renders
as `0.75`, a confident wrong number, which is precisely what the 60px floor existed to prevent.
Halving the floor without the ladder would reintroduce that bug; the ladder is what makes D1 safe.

## The finding that shapes the design

`MIN_BAR_WIDTH` is not a cosmetic constant. Its current value of 60 is a **label-legibility floor**,
not a duration floor — the existing docstring spends a paragraph justifying 60px against the widest
realistic label (`10.75h` ≈ 34px at `text-11`, plus 16px of `px-2`). Lowering it to 30 is therefore
not a one-token edit: it deletes the guarantee the constant was carrying, and the guarantee has to
be re-established somewhere else or the file's own stated invariant is violated.

That is why phase 1 exists. The "does this label fit" question moves out of a hardcoded pixel
constant and into a pure, unit-tested function, where the relationship between font size, padding,
and bar width is explicit and can go red when someone changes a `dayWidth`.

A second consequence, in the other direction: inflating a 1-day bar to 2 days' width at Quarter
could push it visually over the next task in the same lane, since `packTasksIntoLanes` packs by
**date**, not by rendered pixels. Halving the floor strictly reduces that overlap. This change makes
lane packing more honest, not less.

## Phases

| Phase | File | Owns | Estimate |
|---|---|---|---|
| 1 | `phase-1-bar-label-fit.md` | `packages/workload-ext/src/barLabel.ts` (new), its test, `index.ts` export | 1.5h |
| 2 | `phase-2-chart-block.md` | `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx` | 2h |
| 3 | `phase-3-docs-verify.md` | `CLAUDE.md`, `docs/FORK.md`, verification run | 1h |

Phases are sequential: 2 imports what 1 exports, 3 documents what 2 renders.

## Fork discipline

Every file touched is fork-owned — the new `packages/workload-ext` module and the fork's own
`apps/web/core/components/workload/` tree. **No core edit, no new touch-point, no `@plane/*` package
edited in place.** `BLOCK_HEIGHT` (44px) and `VIEWS_LIST[].dayWidth` are read, never written; the
40px Week bar is chosen specifically because it fits inside core's existing row height.

Nothing propagates to `plane-mcp-server` or the SDKs: no endpoint, request field, or response field
changes. The `CLAUDE.md` "Custom features" entry does change, because it already documents the bar's
rendering contract at this level of detail.

## Risk Assessment

| Risk | Likelihood | Impact | Score | Mitigation |
|---|---|---|---|---|
| Character-width heuristic mis-predicts, dropping a label that would have fitted | 3 | 2 | 6 | The heuristic is biased to drop rather than clip — the safe direction. Constants live in one tested file with the font sizes named. |
| 40px Week bar clipped by a core wrapper | 2 | 3 | 6 | Verified: neither `block-row.tsx` nor `block.tsx` sets `overflow: hidden`; both set exactly `BLOCK_HEIGHT` = 44px, so 40px fits with 4px to spare. Confirm visually in phase 3. |
| Losing the name at Month makes bars unreadable for users who navigated by name | 2 | 2 | 4 | The `title` tooltip keeps `identifier + name + hours + split`; Week is unchanged and is the zoom for reading detail. |
| A future `dayWidth` change silently re-breaks the label floor | 3 | 2 | 6 | Phase 1's tests pin the fit boundaries against the three current `dayWidth` values and say so in the failure message. |

No risk scores ≥ 15.

## Timeline

| Phase | Effort | Notes |
|---|---|---|
| Phase 1 — label-fit helper + tests | S (1.5h) | No dependencies; unblocks phase 2 |
| Phase 2 — chart-block rendering | S (2h) | Needs phase 1's export |
| Phase 3 — docs + verify | S (1h) | Needs phase 2 rendered to screenshot |
| **Total** | **4.5h** | Critical path: 1 → 2 → 3 |

## Success criteria

1. Week bars are 40px, two-line, identifier top-left in a smaller dimmed font, name + hours below.
2. Month bars show the estimate alone, centred, with no task name.
3. A 1-day task at Quarter zoom is 30px wide, not 60px.
4. No bar anywhere renders a partial number. `10.75h` either appears whole or does not appear.
5. `pnpm --filter @plane/workload-ext test` green, including new boundary tests.
6. `pnpm check` (typecheck + lint) green.
