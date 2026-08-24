# Phase 2 — per-zoom bar rendering in `WorkloadTimelineChartBlock`

**Owns:** `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`
**Estimate:** 2h
**Depends on:** phase 1 (`hoursLabelStep`, `BAR_LABEL_STEPS` from `@plane/workload-ext`)

## Goal

Render three distinct bar densities from one component, driven by `currentViewData.key`, without
touching the header heat row, the footer, or any block-position arithmetic.

Only the `data.kind === "lane"` branch changes. The `header` branch (capacity heat cells) and the
`footer` branch are out of scope — the user's request is about task bars, and the heat cells already
show hours alone.

## The three bands

`currentViewData.key` is `"week" | "month" | "quarter"`. Replace the existing single `isQuarter`
boolean with an explicit band, because the Month branch now behaves like Quarter rather than like
Week and a negated `isQuarter` would read as the opposite of what it does:

```ts
const isWeek = currentViewData.key === "week";
```

| | Week | Month + Quarter |
|---|---|---|
| bar height | `h-10` (40px) | `h-8` (32px), unchanged |
| lane container | `relative h-10 w-full` | `relative h-8 w-full`, unchanged |
| layout | two lines, `flex-col justify-center items-start` | one line, `justify-center` |
| identifier | `text-9`, dimmed, truncating, line 1 | not rendered |
| name | `text-11`, `min-w-0 flex-1 truncate`, line 2 | **not rendered** (this is the change) |
| hours | `text-11`, `shrink-0 tabular-nums`, line 2 | centred, sized by the phase-1 ladder |

The lane container's height must move with the bar (`h-10` at Week). Neither
`gantt-chart/blocks/block-row.tsx` nor `block.tsx` sets `overflow: hidden` — both set exactly
`BLOCK_HEIGHT` = 44px — so a 40px bar is not clipped, but leaving the container at 32px while the
bars inside it are 40px would make every future reader of this file distrust the alignment.
Verified against those two files; if a core update adds `overflow-hidden` there, this is the line
that breaks.

## `MIN_BAR_WIDTH` — 60 → 30

Change the constant and **rewrite its docstring**. The current one is four paragraphs arguing for
60px as a label-legibility floor, and every sentence of that argument is now false. It must say:

- 30px is a **duration** floor, not a label floor: at Quarter (`dayWidth` 30) it is exactly one
  day, so a 1-day task is drawn one day wide instead of two. The floor now only prevents a
  zero-width bar.
- Legibility moved to `hoursLabelStep` in `@plane/workload-ext` — name the function, so the next
  reader looking for the old guarantee finds where it went.
- The floor still binds **only at Quarter**: a 1-day bar is already 60px at Month and 180px at Week,
  both above 30.
- Halving it strictly *reduces* the visual overlap between adjacent tasks in one lane, since
  `packTasksIntoLanes` packs by date and knows nothing about rendered pixels. The old 60px floor
  could paint a 1-day task over the next day's task; 30px cannot.

## Wiring the ladder

```ts
const label = `${task.hours}h`;
const step = hoursLabelStep(width, label); // `width` is the computed bar width, post-floor
```

Map the step to classes in this file (phase 1 deliberately returns no class strings):

The small step carries `px-0`, not the `px-0.5` this plan first assumed: `10.75h` measures
28px at 9px and the narrowest bar it must serve is 30px, so any padding at all drops the one
label the step was added for. The arithmetic is in `BAR_LABEL_STEPS.small`.

| step | classes on the bar row |
|---|---|
| `"normal"` | `px-2 text-11` |
| `"small"` | `px-0 text-9` |
| `"hidden"` | `px-0` — and render no hours span at all |

**At Week, always render the hours at `"normal"`.** A 180px bar clears the ladder trivially, and
running Week through the same call would let a pathological label shrink the font on a bar with
plenty of room. Call the ladder only in the Month/Quarter branch.

`"hidden"` renders a bare coloured bar. That is intended: the `title` still carries
`identifier + name + hours`, and the peek panel is one click away. Do not substitute a rounded or
abbreviated number — a rounded estimate is the same lie as a clipped one, in fewer characters.

## The Week two-line bar

```
┌────────────────────────┐  h-10, flex-col justify-center, px-2
│ PROJ-142               │  text-9, text-tertiary (or /70 of the bar's own colour), truncate
│ Fix login flow     4h  │  text-11, the existing two-node row
└────────────────────────┘
```

- The identifier is `task.identifier`, already on `TWorkloadTask` (`packages/workload-ext/src/types.ts`)
  and already used in the `title`. **No API change, no new field, no serializer edit.**
- It gets its own `truncate` and must not be allowed to push the second line around — keep the two
  lines as siblings in a `flex-col`, not as a wrapping single text node.
- The existing comment block explaining why name and hours are **two nodes** (a shared text node let
  the name win the ellipsis and eat the estimate) still applies to line 2 verbatim. Keep it; extend
  it to say the identifier is a third node for the same reason.
- Dim the identifier relative to the name so the eye lands on the name first. It is a lookup key,
  not the label.

## Keep unchanged

- The `title` attribute and its assignee-split wording. It is now the *only* place the name survives
  at Month and Quarter, which raises its importance rather than lowering it.
- `getPositionFromDate` / `laneMarginLeft` arithmetic, `WorkloadTaskLink`, the overdue colour
  branch, and the `header` and `footer` branches.
- `BLOCK_HEIGHT`. Nothing in this change touches core.

## Verify

```
pnpm check
```

Then in the running app, on `/:workspaceSlug/workload`, at each zoom:

- **Week** — bars 40px, identifier top-left in a smaller dimmed font, name + hours below, both lines
  inside the bar with no clipping into the row below.
- **Month** — no task names anywhere; a centred `Nh` on every bar.
- **Quarter** — a 1-day task is visibly ~half its previous width. Find a task with a 2-decimal
  estimate and confirm the number is whole or absent, never partial.
- All three — clicking a bar still opens the peek panel; hovering still shows the full tooltip.

The Quarter decimal case is the one to check by hand rather than by reasoning: it is the exact
failure the old 60px floor existed to prevent, and phase 1's heuristic is an estimate, not a
measurement.
