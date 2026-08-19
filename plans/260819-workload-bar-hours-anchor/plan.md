# Workload timeline — always show a bar's estimated hours (right-anchored)

**Created:** 2026-08-19
**Branch:** `fix/workload-bar-hours-anchor`
**Scope:** workload timeline rendering — `workload/timeline/WorkloadTimelineChartBlock.tsx` (Phase 1) and `gantt-chart/views/month-view.ts` (Phase 2, added mid-cook)
**Plane:** [PLANE-76](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/e01b1ca9-354a-4f56-a09e-c40c8c1a6799) — Phase 1, Infrastructure › Plane, 1h
**Plane:** [PLANE-77](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/4afc769a-74e7-4c73-98f4-02714a122cc5) — Phase 2, Infrastructure › Plane, 1h

## Problem

In the workspace Workload timeline, a task bar renders its label as one
truncating span:

```tsx
<span className="truncate">
  {task.name} · {task.hours}h
</span>
```

Because the name and the hours share a single truncated text node, a long work-item
title consumes the whole bar and the estimate — the one number the view exists to
communicate — is the first thing clipped. Visible in the reference screenshot:
`Quest, Setting, Treasure live…` and `Complete map level 1 with ra…` show no hours at
all, while shorter titles like `migrate cat life project to new submodule code · 16h`
happen to fit.

A second, independent cause: the bar's minimum width is `Math.max(endPos - startPos, 8)`
— 8px, far narrower than an `Nh` label, so a one-day task cannot show its estimate even
with no title competing for space.

## Prior art

The task-bar label is rendered in exactly one place. `grep "hours}h"` across
`apps/web/core`, `packages/workload-ext`, and `packages/views-ext` returns only:

| Hit                                  | What it is                                                                                                  |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `WorkloadTimelineChartBlock.tsx:87`  | the bar label being fixed here                                                                              |
| `WorkloadTimelineChartBlock.tsx:80`  | the same bar's `title` tooltip (already carries hours; unchanged)                                           |
| `WorkloadTimelineChartBlock.tsx:133` | the capacity **heat cell** label — a different renderer, already right-sized, out of scope                  |
| `packages/workload-ext/src/i18n.ts`  | `estimate.tooltip` / `estimate.rollup_pill` strings for the **spreadsheet/peek** surfaces, not the timeline |

Zero other timeline bar renderers exist across those paths. `views-ext`'s timeline
layout renders core issue blocks and carries no hours label.

## Decisions (resolved)

| #   | Decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | The bar's minimum rendered width rises from `8` to `60` px so the hours label always renders **whole**. Revised from 36px during implementation: `hours` is a 2-decimal float (`quantize_hours`), so the widest realistic label is `10.75h` (~34px), and the row spends 16px on `px-2` + 6px on `gap-1.5`. Because the hours span is `shrink-0` inside `overflow-hidden`, an undersized bar clips the number's _tail_ — `10.75h` → `10.7` — which is worse than no label. |
| 2   | Title and hours become two flex children — title truncates, hours never shrink. The `·` separator is dropped; a plain gap separates them.                                                                                                                                                                                                                                                                                                                                 |
| 3   | The `title` tooltip keeps its existing full form (`identifier name · Nh · overdue`) — unchanged.                                                                                                                                                                                                                                                                                                                                                                          |

## Phases

| Phase                                                                             | File                                              | Effort    |
| --------------------------------------------------------------------------------- | ------------------------------------------------- | --------- |
| [Phase 1](phase-1.md) — right-anchor the hours, raise min bar width               | `WorkloadTimelineChartBlock.tsx`                  | S (<1h)   |
| [Phase 2](phase-2.md) — month zoom: capacity cells offset from their week columns | `gantt-chart/views/month-view.ts`, `docs/FORK.md` | S (<1h)   |
| [Phase 3](phase-3.md) — week bucket end date a day early west of Greenwich        | `workload-ext/src/dateRange.ts`                   | S (<0.5h) |
| [Phase 4](phase-4.md) — quarter zoom cramped; double each month's width           | `gantt-chart/data/index.ts`, `docs/FORK.md`       | S (<0.5h) |
| [Phase 5](phase-5.md) — quarter zoom: estimate only, drop the bar title           | `WorkloadTimelineChartBlock.tsx`                  | S (<0.5h) |

Only Phase 1 was planned up front. Phases 2 and 4 came from further user reports, Phase 3
from a finding surfaced while reading Phase 2's date math, and Phase 5 after Phase 4's
widening failed to resolve the same complaint. Phases 1–4 have unrelated root causes and
share only the surface they show up on; Phase 4 narrows the distortion Phase 1 accepted,
and Phase 5 supersedes Phase 4's approach to quarter-zoom density (space → content).

## Risk Assessment

| Risk                                                                                                         | Likelihood | Impact | Score | Mitigation                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------ | ---------- | ------ | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| The 60px floor distorts duration at Quarter zoom                                                             | 4          | 2      | 8     | `dayWidth` is 180 (Week) / 60 (Month) / 30 (Quarter, doubled in Phase 4), and a bar is at minimum one full day, so the floor binds **only** at Quarter zoom — and after Phase 4 only on a 1-day task, drawn 2 days wide. Accepted deliberately: at that zoom the chart is read for load, not duration. Week and Month are untouched. |
| `shrink-0` on the hours makes a very narrow bar show hours overflowing the title to zero width               | 2          | 1      | 2     | Intended behaviour per Decision 1 — hours win, title degrades to ellipsis then nothing.                                                                                                                                                                                                                                              |
| Dropping `·` changes the look of bars that previously fit                                                    | 4          | 1      | 4     | Cosmetic and deliberate (Decision 2).                                                                                                                                                                                                                                                                                                |
| An estimate above ~100h _with_ decimals (`100.75h`, ~40px) still overflows the 60px floor's ~38px label room | 1          | 2      | 2     | Outside the realistic range for a single work item; the `title` tooltip carries the exact value either way.                                                                                                                                                                                                                          |

No risk scores ≥ 15.

## Timeline

| Phase     | Effort    | Notes                                                                                                     |
| --------- | --------- | --------------------------------------------------------------------------------------------------------- |
| Phase 1   | S (<1h)   | Single file, no API or package change, no migration                                                       |
| Phase 2   | S (<1h)   | One core file + FORK.md exception row; no API or migration change                                         |
| Phase 3   | S (<0.5h) | One package file; `dist/` is gitignored, nothing to commit                                                |
| Phase 4   | S (<0.5h) | One core file (existing FORK.md exception row, amended)                                                   |
| Phase 5   | S (<0.5h) | One fork-owned file; refines Phases 1 and 4                                                               |
| **Total** | **S**     | Phases are independent; any can ship alone. Phases 1–3 shipped in PR #47, Phase 4 in #48, Phase 5 in #49. |

## Fork discipline

**Phase 1** touches `apps/web/core/components/workload/` only — an existing fork-owned
directory already documented in `docs/FORK.md`.

**Phase 3** touches `packages/workload-ext/` — an existing fork-owned package.

**Phase 2** edits a core file (`gantt-chart/views/month-view.ts`) outside the 7
touch-points, and is therefore recorded in `docs/FORK.md` as the ninth row of the
per-user → workspace-wide week-start conversion table, with a note on why the original
conversion missed it.

Neither phase adds a touch-point, model, or migration. No downstream propagation is
needed (no endpoint, field, or API behaviour changes) — `CLAUDE.md` § "Custom features"
needs no new entry.

## Cook handoff

```
/t1k:cook plans/260819-workload-bar-hours-anchor/
```
