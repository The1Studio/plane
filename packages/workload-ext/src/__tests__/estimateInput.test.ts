/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { parseEstimateHoursInput } from "../estimateInput";

describe("parseEstimateHoursInput", () => {
  it("parses a plain integer", () => {
    expect(parseEstimateHoursInput("4", { allowEmpty: false })).toBe(4);
  });

  it("parses a decimal", () => {
    expect(parseEstimateHoursInput("4.5", { allowEmpty: false })).toBe(4.5);
  });

  it("trims surrounding whitespace", () => {
    expect(parseEstimateHoursInput(" 4.5 ", { allowEmpty: false })).toBe(4.5);
  });

  it("parses a trailing-dot decimal", () => {
    expect(parseEstimateHoursInput("12.", { allowEmpty: false })).toBe(12);
  });

  it("returns null for an empty string when allowEmpty is false — the clearing-to-retype guard", () => {
    expect(parseEstimateHoursInput("", { allowEmpty: false })).toBeNull();
  });

  it("returns 0 for an empty string when allowEmpty is true — explicit clear", () => {
    expect(parseEstimateHoursInput("", { allowEmpty: true })).toBe(0);
  });

  it("returns null for a whitespace-only string when allowEmpty is false", () => {
    expect(parseEstimateHoursInput("   ", { allowEmpty: false })).toBeNull();
  });

  it("returns null for a non-numeric string", () => {
    expect(parseEstimateHoursInput("abc", { allowEmpty: true })).toBeNull();
  });

  it("returns null for a negative number", () => {
    expect(parseEstimateHoursInput("-1", { allowEmpty: true })).toBeNull();
  });

  // Characterization assertion: records what the current code does, not what it ideally should.
  // `Number("1e3")` is 1000 — documents that `Number` accepts scientific notation, matching
  // today's behavior.
  it("accepts scientific notation, matching today's Number() behavior", () => {
    expect(parseEstimateHoursInput("1e3", { allowEmpty: false })).toBe(1000);
  });

  // Characterization assertion: records what the current code does, not what it ideally should.
  // The client does NOT clamp an upper bound — MAX_HOURS is enforced server-side only, so a
  // large value parses through and is rejected (or not) by the server, never silently clamped.
  it("does not clamp a large value client-side", () => {
    expect(parseEstimateHoursInput("99999999", { allowEmpty: false })).toBe(99999999);
  });
});
