/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { BAR_LABEL_STEPS, estimateLabelWidthPx, hoursLabelStep } from "../barLabel";

/**
 * The widths below are not arbitrary — each is the rendered width of a 1-day
 * task bar at one of the three timeline zooms, i.e. `dayWidth` from
 * `apps/web/core/components/gantt-chart/data/index.ts`. That file and this one
 * are coupled: widening or narrowing a zoom changes which cases here matter.
 */
const WEEK_DAY_PX = 180;
const MONTH_DAY_PX = 60;
const QUARTER_DAY_PX = 30; // also MIN_BAR_WIDTH, the narrowest bar that can exist

/** The widest realistic estimate: `hours` is a 2-decimal float, not an integer. */
const WIDE_LABEL = "10.75h";

describe("hoursLabelStep", () => {
  it("renders a common estimate at full size on a Month 1-day bar", () => {
    expect(hoursLabelStep(MONTH_DAY_PX, "4h")).toBe("normal");
  });

  it("still renders a 2-decimal estimate at full size at 60px", () => {
    // 60px is what the old MIN_BAR_WIDTH constant was sized for, and this is
    // the exact case it existed to protect. If this goes red, the guarantee
    // that constant carried has been lost — do NOT fix it by raising the
    // floor back to 60; fix the step metrics.
    expect(hoursLabelStep(MONTH_DAY_PX, WIDE_LABEL)).toBe("normal");
  });

  it("keeps the estimate on the narrowest bar that can exist", () => {
    // A 1-day task at Quarter zoom is the single most common bar at the
    // tightest zoom. Losing its number would empty the view of the one thing
    // it is read for.
    expect(hoursLabelStep(QUARTER_DAY_PX, "4h")).not.toBe("hidden");
  });

  it("steps a 2-decimal estimate down rather than dropping it at 30px", () => {
    // This is the case the small step exists for. If it returns "hidden",
    // either MIN_BAR_WIDTH shrank below 30 or the small step regained
    // horizontal padding it cannot afford — see BAR_LABEL_STEPS.small.
    expect(hoursLabelStep(QUARTER_DAY_PX, WIDE_LABEL)).toBe("small");
  });

  it("drops a label it cannot render whole rather than clipping it", () => {
    // A missing label is recoverable via the bar's title; a clipped one is a
    // wrong number rendered confidently. The ladder must terminate.
    expect(hoursLabelStep(QUARTER_DAY_PX, "105.75h")).toBe("hidden");
  });

  it("never returns a worse step for a wider bar", () => {
    // The property that catches a sign error the point cases above would let
    // through: fitting is monotonic in width.
    const rank: Record<string, number> = { normal: 0, small: 1, hidden: 2 };
    for (const label of ["4h", WIDE_LABEL, "105.75h"]) {
      let previous = Infinity;
      for (let width = 8; width <= WEEK_DAY_PX; width += 2) {
        const current = rank[hoursLabelStep(width, label)];
        expect(current).toBeLessThanOrEqual(previous);
        previous = current;
      }
    }
  });
});

describe("estimateLabelWidthPx", () => {
  it("treats a period as narrower than a digit", () => {
    // Without the dot's own entry every decimal label is over-estimated by
    // ~3px, which is enough to drop a label that would have fitted.
    expect(estimateLabelWidthPx("1.1h", 11)).toBeLessThan(estimateLabelWidthPx("111h", 11));
  });

  it("is biased high, never low, against the step it feeds", () => {
    // The bias direction is the whole safety argument: when this function is
    // wrong it must drop a label, never keep one that overflows. Assert the
    // small step's own worst case has real headroom at its target width
    // rather than merely happening to land on it.
    const { fontPx, paddingPx } = BAR_LABEL_STEPS.small;
    expect(estimateLabelWidthPx(WIDE_LABEL, fontPx) + paddingPx).toBeLessThanOrEqual(QUARTER_DAY_PX);
  });
});
