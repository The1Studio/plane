# Phase 4 — Quarter zoom read as cramped; double each month's width

**Plan:** [plan.md](plan.md)
**Effort:** S (<0.5h)
**Added:** after PR #47 merged, on a fourth report from the user
**Depends on:** nothing, but it narrows Phase 1's `MIN_BAR_WIDTH` distortion (see below)

## Symptom

At **Quarter** zoom the timeline is too dense to read — months are packed so tightly
that bar labels and month headings have no room.

## Why the previous widening did not cover it

The fork already widened all three zooms once (`docs/FORK.md`, "Wider timeline
columns"): week 60→180, month 20→60, quarter 5→15, a uniform ×3.

That uniform factor is the mistake. Quarter zoom does not render **day** columns —
`chart/views/quarter.tsx` renders **month** columns, each sized
`dayWidth * monthBlock.days` (lines 68 and 91). So `dayWidth` at quarter zoom is not a
column width, it is a _thirtieth_ of one. A ×3 that comfortably widened a week-zoom day
column left a 31-day month at only 465px, which is what reads as cramped.

## Change

`apps/web/core/components/gantt-chart/data/index.ts` — quarter `dayWidth` **15 → 30**.

Because a month column is `dayWidth * daysInMonth`, doubling `dayWidth` doubles each
month's rendered width exactly, which is the requested change. Week (180) and month (60)
are untouched.

Net factor from upstream is now ×3 on week and month, **×6 on quarter**. The fork
comment in `data/index.ts` and the `docs/FORK.md` section both said "tripled on all
three views"; both are updated, since that sentence is now false.

## Interaction with Phase 1 (`MIN_BAR_WIDTH = 60`)

Phase 1 set a 60px floor on task-bar width so the `Nh` estimate is never clipped, and
documented that the floor binds **only** at quarter zoom. Doubling `dayWidth` halves how
far it reaches:

|                      | before (`dayWidth` 15)     | after (`dayWidth` 30)      |
| -------------------- | -------------------------- | -------------------------- |
| 1-day bar true width | 15px → drawn 60px (**4×**) | 30px → drawn 60px (**2×**) |
| 2-day bar            | 30px → drawn 60px (2×)     | 60px → **exact**           |
| 3-day bar            | 45px → drawn 60px (1.3×)   | 90px → exact               |

The duration distortion Phase 1 accepted therefore shrinks from "1–3 day tasks, up to
~4 days' worth" to "1-day tasks only, 2 days' worth". `MIN_BAR_WIDTH` itself does not
change — it is sized by the label (`10.75h` + padding + gap), not by the zoom.

The `MIN_BAR_WIDTH` docblock cites the per-zoom `dayWidth` values, so it is updated here
too, with a note to keep the two in step. That docblock is the only place the
floor↔zoom relationship is written down.

## Success criteria

1. `pnpm check:types`, `check:lint` (0 errors), `check:format` all clean.
2. At **Quarter** zoom each month column is exactly twice its previous width, and the
   view no longer reads as cramped.
3. **Week** and **Month** zoom are pixel-identical to before.
4. No stale `quarter 5→15` / `dayWidth ... 15` claim remains in code comments,
   `docs/FORK.md`, or this plan — verified by grep.

## Fork discipline

Edits the same core file already fenced as a `docs/FORK.md` core-edit exception
(`gantt-chart/data/index.ts`); no new touch-point, no new exception row — the existing
row's description is amended. Still deliberately **global**: quarter zoom widens for the
issues, cycles and modules Timeline layouts too, for the same reason recorded when the
original ×3 landed (scoping it to workload would mean threading an override prop through
`GanttChartRoot` and `ChartViewRoot`).
