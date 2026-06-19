/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { route } from "@react-router/dev/routes";
import type { RouteConfigEntry } from "@react-router/dev/routes";

// SP2 — AI feature suite routes (append-only seam, docs/FORK.md touch-point 6).
// Route files live in packages/ai-ext; imported lazily so the package is tree-shaken
// when AI features are disabled at the workspace level.
export const extendedRoutes: RouteConfigEntry[] = [
  route(":workspaceSlug/ai/search", "./(ai)/ai-search-page.tsx"),
  // SP2 workload — per-person hour matrix (docs/FORK.md touch-point 6)
  route(":workspaceSlug/workload", "./(all)/[workspaceSlug]/(projects)/workload/page.tsx"),
];
