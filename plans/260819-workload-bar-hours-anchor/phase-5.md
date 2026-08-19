# Phase 5 — Quarter zoom: show the estimate only, drop the bar title

**Plan:** [plan.md](plan.md)
**Effort:** S (<0.5h)
**Added:** after PR #48 merged, on a fifth report — quarter zoom still read as cramped
**Depends on:** nothing; refines Phases 1 and 4

## Symptom

Doubling each month's width ([Phase 4](phase-4.md)) did not resolve it — quarter zoom
still reads as cramped.

## Why widening was the wrong lever

Phase 4 treated density as a _space_ problem. It is a _content_ problem. At quarter zoom
a task bar is `dayWidth * days` = 30px per day, so a typical 1–3 day bar is 30–90px, of
which 16px is padding and ~34px is the estimate. The title gets whatever is left —
usually nothing, occasionally two or three characters before the ellipsis. Every one of
those bars was paying its entire width to render a fragment that identifies nothing.

Widening the months bought more room but each bar spent it the same way, so the noise
scaled with the space.

## Change

`WorkloadTimelineChartBlock.tsx`, lane branch only:

```tsx
const isQuarter = currentViewData.key === "quarter";
...
{!isQuarter && <span className="min-w-0 flex-1 truncate">{task.name}</span>}
<span className="shrink-0 tabular-nums">{task.hours}h</span>
```

- The title is **dropped**, not truncated, at quarter zoom. Week and month are unchanged.
- With nothing to sit opposite, the estimate **centres** (`justify-center`) instead of
  hugging the right edge, and the `gap-1.5` is dropped since there is only one child.
- The work item's name is unaffected everywhere it is actually readable: the `title`
  tooltip still carries `identifier name · Nh[· overdue]`, and the sidebar still labels
  a single-task lane.

`currentViewData.key` is a plain `string` on `ChartDataType`, so this is a direct
comparison — no enum import.

## Interaction with `MIN_BAR_WIDTH` (Phase 1)

The floor is unchanged at 60px, but its budget improves: quarter zoom is both the only
zoom the floor reaches **and** the only zoom that now drops the title, so there is no
`gap-1.5` to pay for. Label room goes from ~38px to ~44px against a ~34px worst-case
`10.75h`. The docblock is updated to say so — it is the only place that arithmetic is
recorded.

## Success criteria

1. `pnpm check:types`, `check:lint` (0 errors), `check:format` all clean.
2. At **Quarter** zoom every bar shows its estimate only, centred, with no title text
   and no ellipsis.
3. **Week** and **Month** zoom are unchanged — title truncating on the left, estimate
   right-anchored, `gap-1.5` between them.
4. Hovering a quarter-zoom bar still shows the full `identifier name · Nh[· overdue]`
   tooltip, and clicking still opens the peek panel.
5. The capacity heat row is unaffected at every zoom.

## Note

If quarter zoom still reads as dense after this, the remaining levers are the row height
(`h-8`) and the horizontal padding (`px-2`), not the label — there is nothing left in the
bar to remove.
