/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
/**
 * Will a task bar's hours estimate fit inside the bar, and at what size?
 *
 * This module owns a guarantee that used to live inside a single constant.
 * `MIN_BAR_WIDTH` in `WorkloadTimelineChartBlock` was 60px, and its docstring
 * spent four paragraphs justifying that number as a **label-legibility floor**:
 * 60px was the width at which the widest realistic estimate (`10.75h`, ~34px at
 * `text-11`, plus 16px of `px-2`) could still render whole. The bar's label row
 * is `overflow-hidden` and `justify-center`, so a bar too narrow for its label
 * does not truncate politely at the tail — it eats both ends, and `10.75h`
 * renders as a confident, wrong `0.75`.
 *
 * The floor is now 30px, chosen for DURATION (one day at Quarter zoom) rather
 * than for legibility, so the legibility question has to be answered somewhere
 * else. It is answered here, where the relationship between font size, padding
 * and bar width is explicit and testable, instead of being an argument written
 * in prose beside a magic number.
 *
 * The rule the ladder enforces, unchanged from the constant it replaces:
 * **a missing label is recoverable, a truncated one is a lie.** The bar's
 * `title` still carries the full estimate, and the peek panel is one click
 * away, so dropping the number costs the reader a hover. Printing four of its
 * six characters costs them the truth.
 */

/**
 * How wide one character is, as a fraction of the font size.
 *
 * The bars render hours with `tabular-nums`, so every digit has the same
 * advance regardless of which digit it is — that is what makes a table this
 * small able to stand in for real text metrics. A period is roughly half a
 * digit; without its own entry, `10.75h` is over-estimated by ~3px, which is
 * enough to push a label that would have fitted into the next step down.
 */
export const CHAR_EM = {
  /** `0`-`9`, all identical under `tabular-nums`. */
  digit: 0.55,
  /** `.` — the only sub-digit-width character an hours label contains. */
  dot: 0.28,
  /** `h`, and anything else that reaches this table. */
  other: 0.55,
} as const;

/**
 * Estimated rendered width of `label` at `fontPx`, in px.
 *
 * No DOM measurement, deliberately: this has to be callable during render
 * without forcing a layout pass, and testable in vitest without a browser.
 *
 * The estimate is **biased high**, and the bias direction is load-bearing.
 * When this function is wrong, the failure it produces must be "a label that
 * would just have fitted was dropped" — never "a label that would have
 * overflowed was kept". The first failure costs a hover; the second prints a
 * wrong number. If you retune `CHAR_EM`, round up, not down.
 */
export function estimateLabelWidthPx(label: string, fontPx: number): number {
  let em = 0;
  for (const ch of label) {
    if (ch >= "0" && ch <= "9") em += CHAR_EM.digit;
    else if (ch === ".") em += CHAR_EM.dot;
    else em += CHAR_EM.other;
  }
  return Math.ceil(em * fontPx);
}

/**
 * The two sizes a bar's hours label can render at, widest first.
 *
 * `paddingPx` is the HORIZONTAL padding the bar spends on both sides together
 * — the Tailwind class in the comment is the SSOT for what the component
 * actually applies, and the two must be changed together or this module will
 * answer a question about a layout that no longer exists.
 */
export const BAR_LABEL_STEPS = {
  /** `text-11` + `px-2` (8px each side). */
  normal: { fontPx: 11, paddingPx: 16 },
  /**
   * `text-9` + `px-0` — no horizontal padding at all, which is a decision
   * rather than an oversight.
   *
   * The narrowest bar this step exists to serve is 30px (one day at Quarter
   * zoom, the `MIN_BAR_WIDTH` floor), and the widest label it has to carry
   * there is a 2-decimal estimate: `10.75h` measures 28px at 9px. Any padding
   * at all pushes that to 32px and drops the label — so a step that kept even
   * `px-0.5` would be unable to render the one case it was added for, and the
   * ladder would collapse straight from `normal` to `hidden`.
   *
   * 28px of text centred in 30px still leaves a pixel each side, and the bar's
   * own rounded background supplies the visual separation that padding
   * otherwise would.
   */
  small: { fontPx: 9, paddingPx: 0 },
} as const;

/**
 * Which rendering step a bar of `barWidthPx` can afford for `label`.
 *
 * - `"normal"` — render at `text-11` / `px-2`.
 * - `"small"` — render at `text-9` / `px-0`.
 * - `"hidden"` — render no label at all. NOT a licence to render a shortened,
 *   rounded, or abbreviated number instead: a rounded estimate is the same lie
 *   as a clipped one in fewer characters.
 */
export type TBarLabelStep = "normal" | "small" | "hidden";

export function hoursLabelStep(barWidthPx: number, label: string): TBarLabelStep {
  for (const step of ["normal", "small"] as const) {
    const { fontPx, paddingPx } = BAR_LABEL_STEPS[step];
    if (estimateLabelWidthPx(label, fontPx) + paddingPx <= barWidthPx) return step;
  }
  return "hidden";
}
