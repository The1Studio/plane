/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (views-search) — selector hook for `viewsSearchStore`
 * (apps/web/ce/store/root.store.ts). Mirrors `use-workload.ts` verbatim: a
 * package under `packages/` cannot read `StoreContext` (same dependency-
 * direction constraint as D6 in plan.md), so this selector lives in
 * `core/hooks/store/` rather than in `@plane/views-ext`.
 */

import { useContext } from "react";
// mobx store
import { StoreContext } from "@/lib/store-context";
// types
import type { IViewsSearchStore } from "@plane/views-ext";

export const useViewsSearch = (): IViewsSearchStore => {
  const context = useContext(StoreContext);
  if (context === undefined) throw new Error("useViewsSearch must be used within StoreProvider");
  return context.viewsSearchStore;
};
