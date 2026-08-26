/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { STATE_GROUPS } from "@plane/constants";
import { FALLBACK_BAR_COLOR, stateBarColor } from "../stateColor";

/**
 * `stateBarColor` owns the answer to "what colour is this bar", and every
 * branch below is reachable from real data — none of these are contrived.
 * `State.color` is a free `CharField` server-side with no hex validation, and
 * the state groups are an upstream enum this fork does not control.
 */
describe("stateBarColor", () => {
  it("uses the state's own colour when it has one", () => {
    // The point of D1: a custom state keeps its own hue rather than
    // collapsing into its group's.
    expect(stateBarColor({ state_color: "#8b5cf6", state_group: "started" })).toBe("#8b5cf6");
  });

  it("prefers the state's own colour over its group's", () => {
    // Both present — the specific one must win, or every custom state in a
    // group renders identically and the feature buys nothing.
    const result = stateBarColor({ state_color: "#8b5cf6", state_group: "started" });
    expect(result).not.toBe(STATE_GROUPS.started.color);
  });

  it("accepts non-hex CSS colour forms unchanged", () => {
    // The value is opaque and must never be parsed. If someone adds a
    // "looks like #rrggbb" guard, these go red — which is the point.
    expect(stateBarColor({ state_color: "rgb(139, 92, 246)", state_group: "started" })).toBe("rgb(139, 92, 246)");
    expect(stateBarColor({ state_color: "#fa0", state_group: "started" })).toBe("#fa0");
    expect(stateBarColor({ state_color: "rebeccapurple", state_group: "started" })).toBe("rebeccapurple");
  });

  it.each(Object.values(STATE_GROUPS).map((g) => [g.key, g.color]))(
    "falls back to the %s group's colour when the state has none",
    (group, expected) => {
      expect(stateBarColor({ state_color: "", state_group: group })).toBe(expected);
    }
  );

  it("treats a whitespace-only colour as absent", () => {
    // `" "` is a valid CharField value and an invalid CSS colour — the
    // browser would drop it and render the bar unfilled.
    expect(stateBarColor({ state_color: "   ", state_group: "completed" })).toBe(STATE_GROUPS.completed.color);
  });

  it("handles a null or missing colour like a blank one", () => {
    // A client one release behind a server that has not shipped the field
    // sees `undefined` here, not `""`.
    expect(stateBarColor({ state_color: null, state_group: "backlog" })).toBe(STATE_GROUPS.backlog.color);
    expect(stateBarColor({ state_group: "backlog" })).toBe(STATE_GROUPS.backlog.color);
  });

  it("falls back to the accent for a state group outside the known five", () => {
    // `triage` is excluded by `_base_queryset` server-side, so this is a
    // guard against an upstream group added later — not a live path.
    expect(stateBarColor({ state_color: "", state_group: "triage" })).toBe(FALLBACK_BAR_COLOR);
    expect(stateBarColor({ state_color: "", state_group: "" })).toBe(FALLBACK_BAR_COLOR);
  });

  it("never returns an empty string", () => {
    // The contract the caller depends on: whatever goes in, something
    // paintable comes out. An empty string reaching `backgroundColor`
    // renders a transparent — invisible — bar.
    for (const input of [{ state_color: "", state_group: "" }, { state_color: null, state_group: null }, {}]) {
      expect(stateBarColor(input)).not.toBe("");
    }
  });
});
