# Phase 1 — a pure, tested answer to "does this label fit in this bar?"

**Owns:** `packages/workload-ext/src/barLabel.ts` *(new)*,
`packages/workload-ext/src/__tests__/barLabel.test.ts` *(new)*,
`packages/workload-ext/src/index.ts` *(one export line)*
**Estimate:** 1.5h
**Depends on:** nothing

## Goal

Move the label-legibility guarantee out of the `MIN_BAR_WIDTH = 60` constant — where it lives today
as prose in a docstring — and into a function that can be tested and that fails loudly when the
relationship it encodes stops holding.

Phase 2 halves that constant to 30px. The guarantee it was carrying has to exist somewhere first,
or phase 2 is a regression dressed as a feature.

## What to add

```ts
export type TBarLabelStep = "normal" | "small" | "hidden";

/** Estimated rendered width of `label` at `fontPx`, in px. */
export function estimateLabelWidthPx(label: string, fontPx: number): number;

/**
 * Which rendering step a bar of `barWidthPx` can afford for `label`.
 * "normal" → text-11 / px-2 · "small" → text-9 / px-0.5 · "hidden" → render nothing.
 */
export function hoursLabelStep(barWidthPx: number, label: string): TBarLabelStep;
```

### `estimateLabelWidthPx`

No DOM measurement — this must stay pure so it is testable in vitest without a browser and callable
during render without a layout pass. Per-character advance as a fraction of the font size:

| Character class | em | Why |
|---|---|---|
| digit `0-9` | 0.55 | The bars use `tabular-nums`, so every digit has the same advance |
| `.` | 0.28 | A period is roughly half a digit; ignoring this over-estimates `10.75h` by ~3px |
| anything else (`h`, `,`) | 0.55 | The unit suffix is the only other character an hours label contains |

Sum `fontPx * em` per character and round up. Keep the table in one exported const so the test can
assert against it directly rather than re-deriving the arithmetic.

**The estimate is deliberately biased high.** When it is wrong, a label that would have just fitted
gets dropped rather than a label that would have overflowed getting clipped. Dropping is the
recoverable failure — the tooltip still carries the number — so the bias must point that way. Say
this in the docstring; the next person to "fix" the constants needs to know which direction is safe.

### `hoursLabelStep`

Two named step definitions, exported so phase 2 and the tests share one source:

```ts
export const BAR_LABEL_STEPS = {
  normal: { fontPx: 11, paddingPx: 16 }, // text-11 + px-2 (8px each side)
  small: { fontPx: 9, paddingPx: 4 },    // text-9  + px-0.5 (2px each side)
} as const;
```

Return the first step whose `estimateLabelWidthPx(label, fontPx) + paddingPx <= barWidthPx`,
otherwise `"hidden"`.

Phase 2 maps the returned step to Tailwind classes. Do **not** return class strings from this
package: the numbers here have to stay comparable to the pixel widths they are being tested
against, and a class name is not comparable to anything.

## Tests

`__tests__/barLabel.test.ts`. Every case states the zoom it stands for, because the numbers are
only meaningful against the three `dayWidth` values in
`apps/web/core/components/gantt-chart/data/index.ts` (Week 180, Month 60, Quarter 30).

1. **Month, 1-day bar (60px), `"4h"`** → `"normal"`. The common case must not silently degrade to a
   smaller font just because the ladder exists.
2. **Month, 1-day bar (60px), `"10.75h"`** → `"normal"`. 60px is the width the old constant was
   sized for; this is the case that constant existed to protect, and it must still pass at step 1.
3. **Quarter, 1-day bar (30px), `"4h"`** → `"small"` or `"normal"` — assert it is **not**
   `"hidden"`. The single most common bar at the tightest zoom has to keep its number.
4. **Quarter, 1-day bar (30px), `"10.75h"`** → `"small"`. This is the decision D5 exists for.
5. **A pathological label (`"105.75h"`) at 30px** → `"hidden"`. Proves the ladder terminates rather
   than clipping.
6. **Monotonicity:** for a fixed label, widening the bar never returns a *worse* step. Loop a few
   widths and assert the step index is non-increasing. This is the property that catches an
   arithmetic sign error the point cases would let through.
7. **`estimateLabelWidthPx` treats `.` as narrower than a digit** — assert
   `estimateLabelWidthPx("1.1h", 11) < estimateLabelWidthPx("111h", 11)`. Pins the one table entry
   whose absence would silently over-estimate every decimal label into `"hidden"`.

Failure messages must name what a red test means, not just the expected number — e.g. *"a 1-day
Quarter bar can no longer show its estimate; either `dayWidth` changed or the step constants did.
Do not fix this by widening `MIN_BAR_WIDTH` back to 60."* A bare `expected "small" got "hidden"`
sends the next reader to the wrong file.

## Verify

```
pnpm --filter @plane/workload-ext test
```

All 7 cases green. Then deliberately break one — set the `normal` step's `fontPx` to 30 and confirm
cases 1 and 2 go red. A test never seen failing is unproven (`rules/green-that-proves-nothing.md`).

## Do not

- Do not import React, MobX, or anything from `apps/web` here. This module stays pure.
- Do not read `MIN_BAR_WIDTH` from this package — the floor stays in the component that renders it;
  this module only answers the fit question for a width it is handed.
