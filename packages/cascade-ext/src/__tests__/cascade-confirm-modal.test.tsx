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

function openModal(store: CascadeConfirmStore, descendants: TCascadeDescendant[]) {
  const pending = store.requestCascade({ parentIdentifier: "PLANE-1", targetGroup: "completed", descendants });
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
