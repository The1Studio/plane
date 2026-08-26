/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
// Tests for the timeline's PACK WINDOW — the visible span snapped outward to
// whole columns of the current zoom (`columnAlignedWindow` in ../dateRange).
//
// Three properties carry the design and none is visible in a screenshot.
// OUTWARD: the window must always contain the span it was given, because a bar
// inside the viewport but outside the pack window gets no lane and disappears —
// a worse failure than the blank row the window exists to remove. STABLE: two
// viewports inside the same columns must produce the SAME window, or the board
// repacks on every scroll settle and bars jump rows under the cursor. And the
// unit must follow the ZOOM: a fixed unit was tried first (week-aligned) and
// collapsed nothing, because a viewport starting mid-week snaps back and
// re-admits the very off-screen work it was meant to exclude.

import { describe, expect, it } from "vitest";
import { columnAlignedWindow } from "../dateRange";

// 2026-08-22 is a Saturday, 2026-08-24 the Monday after it.
const MONDAY_START = 1;
const SUNDAY_START = 0;

describe("columnAlignedWindow", () => {
  describe("day columns (Week zoom)", () => {
    it("is the viewport plus one day of rounding slack on each side", () => {
      // Not the identity. `getDateFromPositionOnGantt` rounds a pixel to the
      // NEAREST day, so a part-scrolled edge column reports the day beyond it
      // and `from`/`to` land one column inside the visible span. A bar there
      // would get no lane and vanish — which it did, on a real board.
      expect(columnAlignedWindow("2026-08-22", "2026-08-29", "day", MONDAY_START)).toEqual({
        from: "2026-08-21",
        to: "2026-08-30",
      });
    });

    it("keeps a bar in a part-scrolled edge column, the case that regressed", () => {
      // XGAME-15 is dated 08-22 and sat in a column ~60% scrolled off, so the
      // viewport was reported as starting 08-23. Its hours stayed in the heat
      // cell while the bar itself disappeared.
      const win = columnAlignedWindow("2026-08-23", "2026-08-29", "day", MONDAY_START);
      expect(win.from <= "2026-08-22").toBe(true);
    });

    it("does not widen a Saturday start back to its Monday", () => {
      // The regression that retired the week-aligned version. XuanCuong's
      // viewport began on Sat 22nd; snapping to Mon 17th pulled in three tasks
      // dated the 17th, which then owned two lanes nothing could draw into.
      const win = columnAlignedWindow("2026-08-22", "2026-08-29", "day", MONDAY_START);
      expect(win.from).toBe("2026-08-21");
      // The point of the day unit: still nowhere near the Monday a week-aligned
      // window would have snapped back to, so 08-17 work stays excluded.
      expect(win.from > "2026-08-17").toBe(true);
    });

    it("ignores the week-start day, which does not apply to day columns", () => {
      expect(columnAlignedWindow("2026-08-22", "2026-08-29", "day", SUNDAY_START)).toEqual(
        columnAlignedWindow("2026-08-22", "2026-08-29", "day", MONDAY_START)
      );
    });
  });

  describe("week columns (Month zoom)", () => {
    it("snaps both edges outward to the workspace's week boundaries", () => {
      // The slack is absorbed by the snap here: 25th and 29th are still inside
      // the same week as the 26th and 28th.
      expect(columnAlignedWindow("2026-08-26", "2026-08-28", "week", MONDAY_START)).toEqual({
        from: "2026-08-24",
        to: "2026-08-30",
      });
    });

    it("carries the slack into the neighbouring week when the edge is a boundary day", () => {
      // Mon 24th minus a day is Sun 23rd, which belongs to the PREVIOUS week —
      // the slack is applied before the snap precisely so this widens rather
      // than rounding back to the 24th.
      expect(columnAlignedWindow("2026-08-24", "2026-08-30", "week", MONDAY_START)).toEqual({
        from: "2026-08-17",
        to: "2026-09-06",
      });
    });

    it("honours a different week-start day", () => {
      // A hardcoded Monday would silently shift every window by a day for a
      // workspace whose week starts on Sunday.
      expect(columnAlignedWindow("2026-08-26", "2026-08-28", "week", SUNDAY_START)).toEqual({
        from: "2026-08-23",
        to: "2026-08-29",
      });
    });

    it("is stable for any two viewports inside the same weeks", () => {
      // What makes recomputing on scroll tolerable: the equality guard in
      // WorkloadTimelineRoot rejects the update and no block is rebuilt.
      // Both edges are interior days, so the slack cannot reach a boundary.
      expect(columnAlignedWindow("2026-08-26", "2026-08-28", "week", MONDAY_START)).toEqual(
        columnAlignedWindow("2026-08-27", "2026-08-28", "week", MONDAY_START)
      );
    });

    it("crosses a month boundary without losing a day", () => {
      // Mon 31 Aug .. Sun 6 Sep is one week straddling two months; the
      // arithmetic must not be re-derived per calendar month.
      expect(columnAlignedWindow("2026-09-02", "2026-09-03", "week", MONDAY_START)).toEqual({
        from: "2026-08-31",
        to: "2026-09-06",
      });
    });
  });

  describe("month columns (Quarter zoom)", () => {
    it("snaps outward to whole calendar months", () => {
      expect(columnAlignedWindow("2026-08-26", "2026-10-03", "month", MONDAY_START)).toEqual({
        from: "2026-08-01",
        to: "2026-10-31",
      });
    });

    it("lands on the real last day of a short month", () => {
      // Day 0 of the following month, not a 30/31 table — and February is why.
      expect(columnAlignedWindow("2026-02-10", "2026-02-11", "month", MONDAY_START)).toEqual({
        from: "2026-02-01",
        to: "2026-02-28",
      });
    });

    it("handles a leap February", () => {
      expect(columnAlignedWindow("2028-02-10", "2028-02-11", "month", MONDAY_START).to).toBe("2028-02-29");
    });

    it("carries the slack into the neighbouring month on the 1st", () => {
      // The 1st minus a day is the previous month, so the window widens rather
      // than snapping back — the month-column form of the boundary case above.
      expect(columnAlignedWindow("2026-03-01", "2026-03-05", "month", MONDAY_START).from).toBe("2026-02-01");
    });

    it("crosses a year boundary", () => {
      expect(columnAlignedWindow("2026-12-15", "2027-01-05", "month", MONDAY_START)).toEqual({
        from: "2026-12-01",
        to: "2027-01-31",
      });
    });
  });

  it("always contains the span it was given, with at least a day of slack, at any zoom", () => {
    // The invariant that keeps a visible bar from vanishing. Swept across a
    // full week of start days rather than checked on one convenient date.
    for (const granularity of ["day", "week", "month"] as const) {
      for (let offset = 0; offset < 7; offset++) {
        const day = `2026-08-${String(22 + offset).padStart(2, "0")}`;
        const win = columnAlignedWindow(day, day, granularity, MONDAY_START);
        // Strictly outside, not merely touching: a bar on the reported edge day
        // must sit INSIDE the window, never on its boundary by luck.
        expect(win.from < day).toBe(true);
        expect(win.to > day).toBe(true);
      }
    }
  });
});
