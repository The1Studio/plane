# Phase 1 — Right-anchor the estimated hours on a workload timeline bar

**Plan:** [plan.md](plan.md)
**Effort:** S (<1h)
**Depends on:** nothing

## Goal

A workload timeline task bar always shows its estimated hours, right-anchored, no
matter how long the work-item title is or how short the bar is.

## File ownership

| Glob                                                                        | Owner                  |
| --------------------------------------------------------------------------- | ---------------------- |
| `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx` | this phase (exclusive) |

No other file is touched. Do not edit `WorkloadTaskLink.tsx`, `blocks.ts`,
`heat-color.ts`, or anything under `packages/workload-ext/`.

## Changes

All edits are inside the `data.kind === "lane"` branch of
`WorkloadTimelineChartBlock`.

### 1. Raise the minimum bar width

Current (~line 69):

```tsx
const width = Math.max(endPos - startPos, 8);
```

Becomes a named constant so the number's reason is legible, declared next to the
other lane-scope locals:

```tsx
const MIN_BAR_WIDTH = 60;
...
const width = Math.max(endPos - startPos, MIN_BAR_WIDTH);
```

`60`, not `36`. `hours` is a 2-decimal float (`quantize_hours` →
`round(cents / 100, 2)`), so the widest realistic label is `10.75h` (~34px at
`text-11`), and the row spends 16px on `px-2` plus 6px on `gap-1.5`. The hours
span is `shrink-0` inside an `overflow-hidden` row, so an undersized bar clips
the number's **tail** — `10.75h` renders as a wrong `10.7`, worse than no label.

The floor binds only at **Quarter** zoom: `dayWidth` is 180 / 60 / 15 for
Week / Month / Quarter (`gantt-chart/data/index.ts`) and a bar is at minimum one
full day, so Week and Month already clear 60px untouched. At Quarter a 1–3 day
task is drawn up to ~4 days wide — accepted deliberately.

The docblock on the constant must carry that reasoning; a future reader lowering
it back to "something that fits `16h`" reintroduces the clipped-tail bug.

Declare `MIN_BAR_WIDTH` at module scope (above the component), not inside the map
callback.

### 2. Split the label into two flex children

Current (~lines 74–89):

```tsx
<div
  className={cn(
    "flex h-8 w-full cursor-pointer items-center truncate rounded-sm px-2 text-11 font-medium transition-colors",
    ...
  )}
  title={...}
>
  <span className="truncate">
    {task.name} · {task.hours}h
  </span>
</div>
```

Becomes:

```tsx
<div
  className={cn(
    "flex h-8 w-full cursor-pointer items-center gap-1.5 overflow-hidden rounded-sm px-2 text-11 font-medium transition-colors",
    ...
  )}
  title={...}
>
  {/* The title yields; the estimate does not. A long name truncates to an
      ellipsis (and, on a very narrow bar, to nothing) so that `Nh` — the
      number this view exists to communicate — is always the last thing
      standing. `min-w-0` is what lets a flex child shrink below its content
      width and actually truncate. */}
  <span className="min-w-0 flex-1 truncate">{task.name}</span>
  <span className="shrink-0 tabular-nums">{task.hours}h</span>
</div>
```

Notes on the class changes:

- `truncate` moves **off** the flex container (where it did nothing useful once the
  children became separate nodes) and onto the title span; the container gets
  `overflow-hidden` instead so a shrunk-to-zero title cannot bleed past the bar edge.
- `gap-1.5` supplies the separation the removed `·` used to provide (Decision 2).
- `tabular-nums` matches the heat-cell label a few lines below, so hour figures line
  up column-to-column.
- The `·` between name and hours is removed. The `·` inside the `title` tooltip on the
  same element is **not** touched.

### 3. Update the block comment

The existing comment under the label explains why the identifier prefix was dropped.
Extend it (or replace it) to also record why name and hours are now separate nodes —
future readers must not "simplify" them back into one truncating span.

## Success criteria

1. `pnpm check:types` (and `pnpm check` for lint/format) passes with zero new errors.
2. In the workspace Workload timeline at **Week** zoom, a bar whose title is long
   enough to be clipped (e.g. `Quest, Setting, Treasure live…`) still shows its `Nh`
   on the right edge.
3. At **Quarter** zoom a one-day task bar renders at least 60px wide and shows its
   hours whole — no clipped tail such as `10.7`.
   3b. At **Week** and **Month** zoom no bar's width changes (both already exceed the
   floor), verified by comparing against the pre-change view.
4. A bar with a short title renders `name` then a gap then `Nh` — no middot.
5. Hovering any bar still shows the full `identifier name · Nh[· overdue]` tooltip.
6. Clicking a bar still opens the work-item peek panel (unchanged `WorkloadTaskLink`).
7. Overdue bars keep their `bg-danger-subtle` styling; non-overdue keep
   `bg-accent-primary/15`.
8. The capacity **heat row** (the `header` branch) is visually unchanged.

## Verification

```bash
pnpm check:types && pnpm check:lint
```

Then load `/<workspace>/workload/`, cycle the zoom control through Week → Month →
Quarter, and confirm criteria 2–8 at each zoom.

## Out of scope

- The capacity heat-cell renderer (`data.kind === "header"`).
- Sidebar rows (`WorkloadTimelineSidebarRow.tsx`).
- Any `packages/workload-ext/` i18n string — the bar label is not currently
  localized and this phase does not change that.
- The API response shape.
