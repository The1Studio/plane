/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";

import { renderFormattedPayloadDate } from "@plane/utils";

import { getWorkItemCreationDefaults, resolveCreationAssigneeIds } from "../creation-defaults";

describe("resolveCreationAssigneeIds", () => {
  describe("with the member list fetched", () => {
    it("keeps a pick that is still assignable, over the project default", () => {
      expect(
        resolveCreationAssigneeIds({
          currentAssigneeIds: ["u1"],
          currentUserId: "me",
          projectDefaultAssigneeId: "u2",
          assignableMemberIds: ["u1", "u2", "me"],
        })
      ).toEqual(["u1"]);
    });

    it("narrows a partially-valid pick instead of discarding it", () => {
      expect(
        resolveCreationAssigneeIds({
          currentAssigneeIds: ["u1", "u9"],
          currentUserId: "me",
          assignableMemberIds: ["u1", "me"],
        })
      ).toEqual(["u1"]);
    });

    it("falls back to the project default when no pick survives", () => {
      expect(
        resolveCreationAssigneeIds({
          currentAssigneeIds: ["u9"],
          currentUserId: "me",
          projectDefaultAssigneeId: "u2",
          assignableMemberIds: ["u1", "u2", "me"],
        })
      ).toEqual(["u2"]);
    });

    it("skips a project default that is not itself assignable", () => {
      // Mirrors _is_assignable in plane/issue_defaults_ext/defaults.py: a
      // default assignee who has left the project is not a valid fallback.
      expect(
        resolveCreationAssigneeIds({
          currentUserId: "me",
          projectDefaultAssigneeId: "gone",
          assignableMemberIds: ["me"],
        })
      ).toEqual(["me"]);
    });

    it("falls back to the creator when there is no project default", () => {
      expect(resolveCreationAssigneeIds({ currentUserId: "me", assignableMemberIds: ["me", "u1"] })).toEqual(["me"]);
    });

    it("leaves it unassigned when the creator is not assignable and there is no default", () => {
      // A Guest (role 5) is excluded by getProjectMemberIds(id, false), so this
      // is the case the server would refuse anyway.
      expect(resolveCreationAssigneeIds({ currentUserId: "me", assignableMemberIds: ["u1"] })).toEqual([]);
    });

    it("distinguishes a fetched-but-empty roster from an unfetched one", () => {
      expect(resolveCreationAssigneeIds({ currentUserId: "me", assignableMemberIds: [] })).toEqual([]);
      expect(resolveCreationAssigneeIds({ currentUserId: "me", assignableMemberIds: null })).toEqual(["me"]);
    });
  });

  describe("with the member list not fetched yet", () => {
    it("keeps the current pick without filtering it", () => {
      // "u9" is not assignable anywhere, but nothing knows that yet — the
      // correction pass runs once the roster lands.
      expect(
        resolveCreationAssigneeIds({ currentAssigneeIds: ["u9"], currentUserId: "me", assignableMemberIds: null })
      ).toEqual(["u9"]);
    });

    it("prefers the project default over the creator when nothing is picked", () => {
      expect(
        resolveCreationAssigneeIds({ currentUserId: "me", projectDefaultAssigneeId: "u2", assignableMemberIds: null })
      ).toEqual(["u2"]);
    });

    it("returns nothing when there is no candidate at all", () => {
      expect(resolveCreationAssigneeIds({})).toEqual([]);
    });
  });

  it("never yields an id that is undefined, null or empty", () => {
    const result = resolveCreationAssigneeIds({
      currentAssigneeIds: [undefined as unknown as string, "", null as unknown as string],
      currentUserId: "",
      projectDefaultAssigneeId: null,
      assignableMemberIds: null,
    });

    expect(result).toEqual([]);
  });
});

describe("getWorkItemCreationDefaults", () => {
  it("assigns the creator and today's date", () => {
    const result = getWorkItemCreationDefaults({ currentUserId: "user-1", assignableMemberIds: ["user-1"] });

    expect(result.assignee_ids).toEqual(["user-1"]);
    expect(result.target_date).toBe(renderFormattedPayloadDate(new Date()));
  });

  it("returns nothing at all when there is no candidate assignee yet", () => {
    // The failure this guards: spreading `{ assignee_ids: [undefined] }` into
    // the form would post an assignee array the backend cannot resolve, AND
    // would read as "deliberately empty" rather than "unset".
    expect(getWorkItemCreationDefaults({})).toEqual({});
    expect(getWorkItemCreationDefaults({ currentUserId: undefined })).toEqual({});
    expect(getWorkItemCreationDefaults({ currentUserId: null })).toEqual({});
    expect(getWorkItemCreationDefaults({ currentUserId: "" })).toEqual({});
  });

  it("never yields an assignee array containing undefined", () => {
    const result = getWorkItemCreationDefaults({});
    expect(result.assignee_ids ?? []).not.toContain(undefined);
  });

  it("emits an explicitly empty assignee list when the creator is not assignable", () => {
    // Distinct from the `{}` case above: here we KNOW nobody is assignable, so
    // the form must say so rather than leave the field unset.
    const result = getWorkItemCreationDefaults({ currentUserId: "me", assignableMemberIds: ["someone-else"] });

    expect(result.assignee_ids).toEqual([]);
    expect(result.target_date).toBe(renderFormattedPayloadDate(new Date()));
  });

  it("still dates the item when only a project default assignee is known", () => {
    const result = getWorkItemCreationDefaults({ projectDefaultAssigneeId: "u2", assignableMemberIds: ["u2"] });

    expect(result.assignee_ids).toEqual(["u2"]);
    expect(result.target_date).toBe(renderFormattedPayloadDate(new Date()));
  });
});
