/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { CascadeConfirmStore } from "../cascade-confirm-store";
import type { TCascadeDescendant } from "../types";

function descendant(overrides: Partial<TCascadeDescendant> & { id: string }): TCascadeDescendant {
  return {
    identifier: `PLANE-${overrides.id}`,
    name: "A sub-item",
    depth: 1,
    project_id: "project-1",
    project_name: "Plane",
    state_id: "state-started",
    state_name: "In Progress",
    state_group: "started",
    target_state_id: "state-completed",
    eligible: true,
    reason: null,
    ...overrides,
  };
}

describe("CascadeConfirmStore", () => {
  it("ticks every eligible row by default and leaves ineligible rows unticked", () => {
    const store = new CascadeConfirmStore();
    void store.requestCascade({
      parentIdentifier: "PLANE-1",
      targetGroup: "completed",
      descendants: [descendant({ id: "a", eligible: true }), descendant({ id: "b", eligible: false })],
    });

    expect(store.checkedIds.has("a")).toBe(true);
    expect(store.checkedIds.has("b")).toBe(false);
  });

  it("untick a row removes only that id from the resolved childIds", async () => {
    const store = new CascadeConfirmStore();
    const pending = store.requestCascade({
      parentIdentifier: "PLANE-1",
      targetGroup: "completed",
      descendants: [descendant({ id: "a" }), descendant({ id: "b" })],
    });

    store.toggleChild("a");
    store.confirmCascade();

    const result = await pending;
    expect(result).toEqual({ cascade: true, childIds: ["b"] });
  });

  it("ineligible rows are never toggleable, however many times toggled", async () => {
    const store = new CascadeConfirmStore();
    const pending = store.requestCascade({
      parentIdentifier: "PLANE-1",
      targetGroup: "completed",
      descendants: [descendant({ id: "a", eligible: true }), descendant({ id: "b", eligible: false })],
    });

    store.toggleChild("b");
    store.toggleChild("b");
    store.confirmCascade();

    const result = await pending;
    expect(result).toEqual({ cascade: true, childIds: ["a"] });
  });

  it("unticking every row and confirming cascade resolves cascade:true with an empty childIds", async () => {
    const store = new CascadeConfirmStore();
    const pending = store.requestCascade({
      parentIdentifier: "PLANE-1",
      targetGroup: "completed",
      descendants: [descendant({ id: "a" }), descendant({ id: "b" })],
    });

    store.toggleChild("a");
    store.toggleChild("b");
    store.confirmCascade();

    const result = await pending;
    expect(result).toEqual({ cascade: true, childIds: [] });
  });

  it("confirmOnlyParent resolves cascade:false", async () => {
    const store = new CascadeConfirmStore();
    const pending = store.requestCascade({
      parentIdentifier: "PLANE-1",
      targetGroup: "completed",
      descendants: [descendant({ id: "a" })],
    });

    store.confirmOnlyParent();

    const result = await pending;
    expect(result).toEqual({ cascade: false });
    expect(store.pendingRequest).toBeNull();
  });
});
