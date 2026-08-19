# Phase 2 — Month zoom: capacity heat cells offset from their week columns

**Plan:** [plan.md](plan.md)
**Effort:** S (<1h)
**Added:** mid-cook, on a second report from the user
**Depends on:** nothing (independent of Phase 1)

## Symptom

At **Month** zoom on the workspace Workload timeline, every capacity heat cell in
the header row sits out of step with the week column drawn beneath it. Week and
Quarter zoom are correct.

## Root cause

`ChartViewRoot` reads the workspace week start and passes it to every view's
generator (`gantt-chart/chart/root.tsx:108,120`):

```ts
const startOfWeek = workSettings.week_start_day as EStartOfTheWeek;
...
currentViewHelpers.generateChart(selectedCurrentViewData, side, targetDate, startOfWeek);
```

`generateWeekChart` accepts a fourth parameter. `generateMonthChart` declared only
three, so the argument was **silently discarded**, and its internal call

```ts
getWeeksBetweenTwoDates(startDate, endDate, false); // 4th arg omitted
```

fell through to that function's own `startOfWeek: EStartOfTheWeek = EStartOfTheWeek.SUNDAY`
default. Month zoom therefore drew Sunday-aligned week columns — and set the chart's
own `startDate` to a Sunday — no matter what the workspace had configured.

The workload timeline's heat cells are positioned by their **true calendar dates**
(`periodDateRange` → `getPositionFromDate`), and the API buckets those weeks by
`WorkloadSettings.week_start_day`, whose default is **MONDAY**
(`plane/workload/constants.py`; the deliberate divergence from core's Sunday is
documented in `docs/FORK.md`). Monday-start cells over Sunday-start columns are a
full day column apart — 60px at month zoom's `dayWidth`.

Quarter zoom builds no week blocks at all (`quarter-view.ts` never calls
`getWeeksBetweenTwoDates`) and is unaffected.

Upstream never sees this: upstream's own week-start default is Sunday, which happens
to match the discarded parameter's fallback.

## Change

`apps/web/core/components/gantt-chart/views/month-view.ts` — thread the parameter:

1. `generateMonthChart(monthPayload, side, targetDate, startOfWeek = EStartOfTheWeek.SUNDAY)`
2. `getMonthsViewBetweenTwoDates(startDate, endDate, startOfWeek = EStartOfTheWeek.SUNDAY)`
3. `getWeeksBetweenTwoDates(startDate, endDate, false, startOfWeek)` at all three call sites
4. `import { EStartOfTheWeek } from "@plane/types"`

The `EStartOfTheWeek.SUNDAY` defaults are kept on both signatures so the functions
stay callable by any upstream code path that does not supply the argument.

A pre-existing `no-unmodified-loop-condition` warning in the untouched
`getMonthsBetweenTwoDates` loop is suppressed with an `oxlint-disable-next-line`
comment, matching the precedent already in this fork
(`gantt-chart/chart/root.tsx:168`, `dropdowns/date.tsx:177`). The husky
`lint-staged` gate runs `oxlint --deny-warnings` over the whole staged file, so an
untouched pre-existing warning otherwise blocks the commit.

## Fork discipline

This is a **core-file edit** outside the 7 touch-points, and is recorded in
`docs/FORK.md` as the ninth row of the per-user → workspace-wide week-start
conversion table, with a note explaining why it was missed: the other eight sites
were found by grepping for reads of `start_of_the_week`, and this one had no read
— only a default-valued parameter that was passed but never accepted.

## Success criteria

1. `pnpm check:types`, `check:lint` (0 errors), `check:format` all clean.
2. At **Month** zoom, each capacity heat cell aligns exactly with the week column
   under it, for a workspace whose week start is not Sunday.
3. **Week** and **Quarter** zoom are visually unchanged.
4. Setting the workspace week start to Sunday leaves month zoom identical to its
   pre-change rendering (proves the default is preserved).
5. Non-workload Timeline layouts (issues, cycles, modules) at month zoom now also
   honour the workspace week start — an intended consequence, matching week zoom.
