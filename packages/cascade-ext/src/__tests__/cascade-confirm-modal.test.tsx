/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
// Runtime registration also happens via vitest.config.ts's `setupFiles` (outside this package's
// tsconfig `include`, so it can't carry the TYPE augmentation for `tsc --noEmit`). Importing it
// here too is a redundant but harmless side effect — this is what makes `toBeInTheDocument()` /
// `toBeDisabled()` / `toBeChecked()` below type-check. Namespace-imported (not a bare
// `import "...";`) so oxlint's `no-unassigned-import` doesn't flag it.
import * as jestDomVitestMatchers from "@testing-library/jest-dom/vitest";
void jestDomVitestMatchers;
import { CascadeConfirmModal } from "../cascade-confirm-modal";
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

function openModal(store: CascadeConfirmStore, descendants: TCascadeDescendant[]) {
  const pending = store.requestCascade({ parentIdentifier: "PLANE-1", targetGroup: "completed", descendants });
  render(<CascadeConfirmModal store={store} />);
  return pending;
}

function openModuleModal(
  store: CascadeConfirmStore,
  items: TCascadeItem[],
  overrides: { summary?: TModuleCascadeSummary; overCap?: boolean; cap?: number } = {}
) {
  const summary: TModuleCascadeSummary = overrides.summary ?? {
    total_live: items.length,
    eligible: items.filter((i) => i.eligible).length,
    ineligible: items.filter((i) => !i.eligible).length,
    already_terminal: 0,
  };
  const pending = store.requestModuleCascade({
    moduleName: "Sprint 12",
    targetGroup: "completed",
    items,
    summary,
    overCap: overrides.overCap ?? false,
    cap: overrides.cap ?? 100,
  });
  render(<CascadeConfirmModal store={store} />);
  return pending;
}

describe("CascadeConfirmModal", () => {
  it("holds initial focus on 'Only change this item' — not on a row checkbox", async () => {
    const store = new CascadeConfirmStore();
    openModal(store, [descendant({ id: "a" }), descendant({ id: "b" })]);

    const onlyParentButton = await screen.findByRole("button", { name: "Only change this item" });
    // `waitFor` re-checks after the microtask queue drains, so this also proves headlessUI's own
    // FocusTrap default-focus check (deferred to a microtask — see cascade-confirm-modal.tsx's
    // comment) does not steal focus back onto the first checkbox once this effect has run.
    await waitFor(() => {
      expect(document.activeElement).toBe(onlyParentButton);
    });
  });

  it("pressing Enter immediately on open resolves { cascade: false } — never cascades by accident", async () => {
    const user = userEvent.setup();
    const store = new CascadeConfirmStore();
    const pending = openModal(store, [descendant({ id: "a" })]);

    const onlyParentButton = await screen.findByRole("button", { name: "Only change this item" });
    await waitFor(() => expect(document.activeElement).toBe(onlyParentButton));

    await user.keyboard("{Enter}");

    await expect(pending).resolves.toEqual({ cascade: false });
  });

  it("renders an ineligible row disabled with its reason, and never includes it in childIds", async () => {
    const user = userEvent.setup();
    const store = new CascadeConfirmStore();
    const pending = openModal(store, [
      descendant({ id: "a", eligible: true }),
      descendant({ id: "b", eligible: false, reason: "no_matching_state" }),
    ]);

    expect(await screen.findByText("No matching state in this project")).toBeInTheDocument();
    const ineligibleCheckbox = screen.getByRole("checkbox", { name: "Change PLANE-b too" });
    expect(ineligibleCheckbox).toBeDisabled();
    expect(ineligibleCheckbox).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Change sub-items too" }));

    await expect(pending).resolves.toEqual({ cascade: true, childIds: ["a"] });
  });

  it("unticking a row via the checkbox excludes it from the resolved childIds", async () => {
    const user = userEvent.setup();
    const store = new CascadeConfirmStore();
    const pending = openModal(store, [descendant({ id: "a" }), descendant({ id: "b" })]);

    await user.click(screen.getByRole("checkbox", { name: "Change PLANE-a too" }));
    await user.click(screen.getByRole("button", { name: "Change sub-items too" }));

    await expect(pending).resolves.toEqual({ cascade: true, childIds: ["b"] });
  });
});

describe("CascadeConfirmModal — module subject", () => {
  it("3 items renders the full list expanded, with no disclosure", async () => {
    const store = new CascadeConfirmStore();
    openModuleModal(store, [moduleItem({ id: "a" }), moduleItem({ id: "b" }), moduleItem({ id: "c" })]);

    expect(await screen.findByRole("checkbox", { name: "Change PLANE-a too" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Change PLANE-b too" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Change PLANE-c too" })).toBeInTheDocument();
    expect(screen.queryByText(/Show all/)).not.toBeInTheDocument();
  });

  it("40 items starts collapsed behind a disclosure naming the count, and expands on click", async () => {
    const user = userEvent.setup();
    const store = new CascadeConfirmStore();
    const items = Array.from({ length: 40 }, (_, i) => moduleItem({ id: `item-${i}` }));
    openModuleModal(store, items);

    const disclosure = await screen.findByRole("button", { name: "Show all 40 items" });
    expect(screen.queryByRole("checkbox", { name: "Change PLANE-item-0 too" })).not.toBeInTheDocument();

    await user.click(disclosure);

    expect(await screen.findByRole("checkbox", { name: "Change PLANE-item-0 too" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Change PLANE-item-39 too" })).toBeInTheDocument();
  });

  it("over-cap renders refusal mode: no cascade button, cap and total both rendered, status still changes", async () => {
    const user = userEvent.setup();
    const store = new CascadeConfirmStore();
    const pending = openModuleModal(store, [], {
      summary: { total_live: 240, eligible: 0, ineligible: 0, already_terminal: 0 },
      overCap: true,
      cap: 100,
    });

    expect(await screen.findByText(/240 work items/)).toBeInTheDocument();
    expect(screen.getByText(/100 this action can change/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change work items too" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Only change this module" }));

    await expect(pending).resolves.toEqual({ cascade: false });
  });

  it("holds initial focus on 'Only change this module' — normal mode", async () => {
    const store = new CascadeConfirmStore();
    openModuleModal(store, [moduleItem({ id: "a" })]);

    const onlyModuleButton = await screen.findByRole("button", { name: "Only change this module" });
    await waitFor(() => {
      expect(document.activeElement).toBe(onlyModuleButton);
    });
  });

  it("holds initial focus on 'Only change this module' — refusal mode too", async () => {
    const store = new CascadeConfirmStore();
    openModuleModal(store, [], {
      summary: { total_live: 240, eligible: 0, ineligible: 0, already_terminal: 0 },
      overCap: true,
      cap: 100,
    });

    const onlyModuleButton = await screen.findByRole("button", { name: "Only change this module" });
    await waitFor(() => {
      expect(document.activeElement).toBe(onlyModuleButton);
    });
  });

  it("omits a zero-valued summary clause instead of rendering '0 already done'", async () => {
    const store = new CascadeConfirmStore();
    openModuleModal(store, [moduleItem({ id: "a" }), moduleItem({ id: "b" })], {
      summary: { total_live: 2, eligible: 2, ineligible: 0, already_terminal: 0 },
    });

    expect(await screen.findByText("2 work items will be completed")).toBeInTheDocument();
    expect(screen.queryByText(/already done/)).not.toBeInTheDocument();
    expect(screen.queryByText(/you cannot change/)).not.toBeInTheDocument();
  });

  it("renders every non-zero summary clause together", async () => {
    const store = new CascadeConfirmStore();
    openModuleModal(store, [moduleItem({ id: "a" })], {
      summary: { total_live: 62, eligible: 47, ineligible: 3, already_terminal: 12 },
    });

    expect(
      await screen.findByText("47 work items will be completed · 12 already done · 3 you cannot change")
    ).toBeInTheDocument();
  });
});
