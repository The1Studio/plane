/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { CascadeConfirmStore } from "../cascade-confirm-store";
import type { TCascadeDescendant, TCascadeItem, TModuleCascadeSummary } from "../types";

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

function moduleItem(overrides: Partial<TCascadeItem> & { id: string }): TCascadeItem {
  return { ...descendant(overrides), is_module_member: true, ...overrides };
}

const SUMMARY: TModuleCascadeSummary = { total_live: 2, eligible: 2, ineligible: 0, already_terminal: 0 };

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

describe("CascadeConfirmStore — module subject (requestModuleCascade)", () => {
  it("resolves cascade:true with the ticked childIds on confirmCascade", async () => {
    const store = new CascadeConfirmStore();
    const pending = store.requestModuleCascade({
      moduleName: "Sprint 12",
      targetGroup: "completed",
      items: [moduleItem({ id: "a" }), moduleItem({ id: "b" })],
      summary: SUMMARY,
      overCap: false,
      cap: 100,
    });

    store.toggleChild("a");
    store.confirmCascade();

    const result = await pending;
    expect(result).toEqual({ cascade: true, childIds: ["b"] });
  });

  it("resolves cascade:false on confirmOnlyParent, same as the issue subject", async () => {
    const store = new CascadeConfirmStore();
    const pending = store.requestModuleCascade({
      moduleName: "Sprint 12",
      targetGroup: "completed",
      items: [moduleItem({ id: "a" })],
      summary: SUMMARY,
      overCap: false,
      cap: 100,
    });

    store.confirmOnlyParent();

    const result = await pending;
    expect(result).toEqual({ cascade: false });
    expect(store.pendingRequest).toBeNull();
  });

  it("ticks every eligible item by default, mirroring the issue subject", () => {
    const store = new CascadeConfirmStore();
    void store.requestModuleCascade({
      moduleName: "Sprint 12",
      targetGroup: "completed",
      items: [moduleItem({ id: "a", eligible: true }), moduleItem({ id: "b", eligible: false })],
      summary: SUMMARY,
      overCap: false,
      cap: 100,
    });

    expect(store.checkedIds.has("a")).toBe(true);
    expect(store.checkedIds.has("b")).toBe(false);
  });

  it("select-all / select-none over an over-cap request always resolves { cascade: false, childIds: [] }", async () => {
    const store = new CascadeConfirmStore();
    // Over cap: the modal never renders a list or a cascade button for this request, so
    // `checkedIds` starts empty and the only reachable action is `confirmOnlyParent`.
    const pending = store.requestModuleCascade({
      moduleName: "Sprint 12",
      targetGroup: "completed",
      items: [],
      summary: { total_live: 240, eligible: 0, ineligible: 0, already_terminal: 0 },
      overCap: true,
      cap: 100,
    });

    expect(store.checkedIds.size).toBe(0);
    store.confirmOnlyParent();

    const result = await pending;
    expect(result).toEqual({ cascade: false });
  });

  it("pendingRequest carries kind: 'module' so the modal can distinguish subjects", () => {
    const store = new CascadeConfirmStore();
    void store.requestModuleCascade({
      moduleName: "Sprint 12",
      targetGroup: "cancelled",
      items: [moduleItem({ id: "a" })],
      summary: SUMMARY,
      overCap: false,
      cap: 100,
    });

    expect(store.pendingRequest?.kind).toBe("module");
  });
});

// Guards against the module widening accidentally changing the issue subject's own tag.
describe("CascadeConfirmStore — issue subject still tags kind: 'issue'", () => {
  it("pendingRequest carries kind: 'issue' after requestCascade", () => {
    const store = new CascadeConfirmStore();
    void store.requestCascade({
      parentIdentifier: "PLANE-1",
      targetGroup: "completed",
      descendants: [descendant({ id: "a" })],
    });

    expect(store.pendingRequest?.kind).toBe("issue");
  });
});
