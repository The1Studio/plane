/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
// Namespace-imported (not a bare `import "...";`) so oxlint's `no-unassigned-import` doesn't flag
// an otherwise-legitimate side-effect import — its only job is registering vitest's matchers.
import * as jestDomVitestMatchers from "@testing-library/jest-dom/vitest";
void jestDomVitestMatchers;

// `@testing-library/react`'s own auto-cleanup only registers itself when it finds a global
// `afterEach` (the Jest-style convention) — this project deliberately runs without
// `test.globals: true`, so it's registered explicitly here. Without it, one test's rendered
// modal is still in the DOM when the next test renders another, and role/label queries that
// expect exactly one match start finding two.
afterEach(() => {
  cleanup();
});

// jsdom doesn't implement ResizeObserver, and headlessUI's Dialog (packages/ui's ModalCore)
// reads it on mount to track its panel size. Without this stub, that effect throws
// `ReferenceError: ResizeObserver is not defined`, which aborts the rest of that commit's
// passive-effect flush — including the modal's own initial-focus effect — so every test that
// renders CascadeConfirmModal needs this, not just the ones that assert on focus.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
