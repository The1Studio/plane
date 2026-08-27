/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { parseWorkloadFilterParams, writeWorkloadFilterParams } from "../filterParams";

describe("parseWorkloadFilterParams", () => {
  it("reads all three filters from a comma-joined query string", () => {
    const parsed = parseWorkloadFilterParams(
      new URLSearchParams("project_ids=p1,p2&assignee_ids=a1&state_group=started,backlog")
    );
    expect(parsed).toEqual({
      projectIds: ["p1", "p2"],
      assigneeIds: ["a1"],
      stateGroups: ["started", "backlog"],
    });
  });

  it("reads an absent param as no filtering", () => {
    expect(parseWorkloadFilterParams(new URLSearchParams(""))).toEqual({
      projectIds: [],
      assigneeIds: [],
      stateGroups: [],
    });
  });

  it("reads an empty param as no filtering, not as an empty-string id", () => {
    expect(parseWorkloadFilterParams(new URLSearchParams("project_ids=")).projectIds).toEqual([]);
  });

  it("trims whitespace and drops empty segments from a hand-edited URL", () => {
    expect(parseWorkloadFilterParams(new URLSearchParams("project_ids= p1 ,,p2,")).projectIds).toEqual(["p1", "p2"]);
  });

  it("de-duplicates repeated ids", () => {
    expect(parseWorkloadFilterParams(new URLSearchParams("assignee_ids=a1,a1,a2")).assigneeIds).toEqual(["a1", "a2"]);
  });

  it("drops unknown state groups rather than filtering the board to nothing", () => {
    expect(parseWorkloadFilterParams(new URLSearchParams("state_group=started,not_a_group")).stateGroups).toEqual([
      "started",
    ]);
  });
});

describe("writeWorkloadFilterParams", () => {
  it("writes a selection back as a comma-joined param", () => {
    const next = writeWorkloadFilterParams(new URLSearchParams(""), { projectIds: ["p1", "p2"] });
    expect(next.get("project_ids")).toBe("p1,p2");
  });

  it("omits an empty selection entirely instead of writing a bare key", () => {
    const next = writeWorkloadFilterParams(new URLSearchParams("project_ids=p1"), { projectIds: [] });
    expect(next.has("project_ids")).toBe(false);
    expect(next.toString()).toBe("");
  });

  it("clears every filter when the whole selection is emptied", () => {
    const next = writeWorkloadFilterParams(new URLSearchParams("project_ids=p1&assignee_ids=a1&state_group=started"), {
      projectIds: [],
      assigneeIds: [],
      stateGroups: [],
    });
    expect(next.toString()).toBe("");
  });

  it("leaves filters the patch omits untouched", () => {
    const next = writeWorkloadFilterParams(new URLSearchParams("project_ids=p1&assignee_ids=a1"), {
      stateGroups: ["started"],
    });
    expect(next.get("project_ids")).toBe("p1");
    expect(next.get("assignee_ids")).toBe("a1");
    expect(next.get("state_group")).toBe("started");
  });

  it("preserves unrelated params", () => {
    const next = writeWorkloadFilterParams(new URLSearchParams("peekId=i1"), { projectIds: ["p1"] });
    expect(next.get("peekId")).toBe("i1");
  });

  it("does not mutate the params it was given", () => {
    const current = new URLSearchParams("project_ids=p1");
    writeWorkloadFilterParams(current, { projectIds: ["p2"] });
    expect(current.get("project_ids")).toBe("p1");
  });

  it("round-trips a selection through parse", () => {
    const selection = { projectIds: ["p1", "p2"], assigneeIds: ["a1"], stateGroups: ["completed"] };
    expect(parseWorkloadFilterParams(writeWorkloadFilterParams(new URLSearchParams(""), selection))).toEqual(selection);
  });
});
