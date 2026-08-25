import { describe, expect, it } from "vitest";

import type { TIssue } from "@plane/types";

import { getProjectChangeFormReset } from "../project-change";

const formValues = (overrides: Partial<TIssue> = {}): Partial<TIssue> => ({
  project_id: "old-project",
  name: "Fix the thing",
  description_html: "<p>context</p>",
  priority: "high",
  start_date: "2026-08-24",
  target_date: "2026-08-27",
  assignee_ids: ["u1"],
  state_id: "old-state",
  label_ids: ["l1"],
  cycle_id: "c1",
  module_ids: ["m1"],
  ...overrides,
});

describe("getProjectChangeFormReset", () => {
  it("carries both dates across a project change untouched", () => {
    const result = getProjectChangeFormReset("new-project", formValues(), { currentUserId: "me" });

    expect(result.start_date).toBe("2026-08-24");
    expect(result.target_date).toBe("2026-08-27");
  });

  it("never re-fills a due date the user deliberately cleared", () => {
    // The regression this pins: re-asserting the creation default here would
    // resurrect a cleared due date on every project switch, and the user could
    // never actually save an item without one. There is no start_date default
    // on either side of this fork, so a null start_date must stay null too.
    const result = getProjectChangeFormReset("new-project", formValues({ target_date: null, start_date: null }), {
      currentUserId: "me",
      assignableMemberIds: ["me"],
    });

    expect(result.target_date).toBeNull();
    expect(result.start_date).toBeNull();
  });

  it("carries the other non-project-scoped fields across", () => {
    // Guards against an upstream change narrowing what getUpdateFormDataForReset
    // preserves — that helper is in the sealed @plane/utils package, so a rebase
    // can move it without touching anything here.
    const result = getProjectChangeFormReset("new-project", formValues(), { currentUserId: "me" });

    expect(result.name).toBe("Fix the thing");
    expect(result.description_html).toBe("<p>context</p>");
    expect(result.priority).toBe("high");
    expect(result.project_id).toBe("new-project");
  });

  it("still clears the project-scoped fields", () => {
    const result = getProjectChangeFormReset("new-project", formValues(), { currentUserId: "me" });

    expect(result.state_id).toBe("");
    expect(result.label_ids).toEqual([]);
    expect(result.cycle_id).toBeNull();
    expect(result.module_ids).toBeNull();
  });

  it("re-resolves the assignee for the new project instead of emptying it", () => {
    const result = getProjectChangeFormReset("new-project", formValues({ assignee_ids: ["u1"] }), {
      currentUserId: "me",
      projectDefaultAssigneeId: "u2",
      assignableMemberIds: ["u2", "me"],
    });

    // "u1" is not a member of the new project, so the project default wins.
    expect(result.assignee_ids).toEqual(["u2"]);
  });

  it("keeps a selected assignee who is also a member of the new project", () => {
    const result = getProjectChangeFormReset("new-project", formValues({ assignee_ids: ["u1"] }), {
      currentUserId: "me",
      projectDefaultAssigneeId: "u2",
      assignableMemberIds: ["u1", "u2", "me"],
    });

    expect(result.assignee_ids).toEqual(["u1"]);
  });

  it("takes the selection from the form when the caller does not pass one", () => {
    const result = getProjectChangeFormReset("new-project", formValues({ assignee_ids: ["u1"] }), {
      currentUserId: "me",
      assignableMemberIds: ["u1", "me"],
    });

    expect(result.assignee_ids).toEqual(["u1"]);
  });

  it("lets an explicitly empty selection stay empty rather than reading the form", () => {
    // `[]` from the caller is "the user cleared it", not "I have nothing to say".
    const result = getProjectChangeFormReset("new-project", formValues({ assignee_ids: ["u1"] }), {
      currentAssigneeIds: [],
      currentUserId: "me",
      assignableMemberIds: ["u1", "me"],
    });

    expect(result.assignee_ids).toEqual(["me"]);
  });
});
