import { describe, expect, it } from "vitest";

import { renderFormattedPayloadDate } from "@plane/utils";

import { getWorkItemCreationDefaults } from "../creation-defaults";

describe("getWorkItemCreationDefaults", () => {
  it("assigns the creator and today's date", () => {
    const result = getWorkItemCreationDefaults("user-1");

    expect(result.assignee_ids).toEqual(["user-1"]);
    expect(result.target_date).toBe(renderFormattedPayloadDate(new Date()));
  });

  it("returns nothing at all when the user is not loaded yet", () => {
    // The failure this guards: spreading `{ assignee_ids: [undefined] }` into
    // the form would post an assignee array the backend cannot resolve, AND
    // would read as "deliberately empty" rather than "unset".
    expect(getWorkItemCreationDefaults(undefined)).toEqual({});
    expect(getWorkItemCreationDefaults(null)).toEqual({});
    expect(getWorkItemCreationDefaults("")).toEqual({});
  });

  it("never yields an assignee array containing undefined", () => {
    const result = getWorkItemCreationDefaults(undefined);
    expect(result.assignee_ids ?? []).not.toContain(undefined);
  });
});
