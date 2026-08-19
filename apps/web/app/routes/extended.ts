/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { layout, route } from "@react-router/dev/routes";
import type { RouteConfigEntry } from "@react-router/dev/routes";

// SP2 — AI feature suite routes (append-only seam, docs/FORK.md touch-point 6).
// Route files live in packages/ai-ext; imported lazily so the package is tree-shaken
// when AI features are disabled at the workspace level.
export const extendedRoutes: RouteConfigEntry[] = [
  route(":workspaceSlug/ai/search", "./(ai)/ai-search-page.tsx"),
  // SP2 workload — per-person hour matrix (docs/FORK.md touch-point 6).
  // Wrapped in the same layout chain as core workspace routes so mergeRoutes
  // deep-merges it into the (projects) shell (sidebar + workspace providers).
  layout("./(all)/layout.tsx", [
    layout("./(all)/[workspaceSlug]/layout.tsx", [
      layout("./(all)/[workspaceSlug]/(projects)/layout.tsx", [
        // Nested in its own layout so the tab mounts an <AppHeader>, the same
        // as every core workspace page. Without it the app-sidebar toggle never
        // renders and a collapsed sidebar cannot be reopened from this tab.
        layout("./(all)/[workspaceSlug]/(projects)/workload/layout.tsx", [
          route(":workspaceSlug/workload", "./(all)/[workspaceSlug]/(projects)/workload/page.tsx"),
        ]),
      ]),
    ]),
  ]),
  // The1Studio fork (workspace work settings) — workspace settings page for
  // max weekly hours / workdays / first day of week (docs/FORK.md touch-point 6).
  // Mirrors the (settings) chain from core.ts:258-284 exactly so mergeRoutes
  // deep-merges this route into the SAME settings shell (single sidebar),
  // rather than instantiating a second settings layout.
  layout("./(all)/layout.tsx", [
    layout("./(all)/[workspaceSlug]/layout.tsx", [
      layout("./(all)/[workspaceSlug]/(settings)/layout.tsx", [
        layout("./(all)/[workspaceSlug]/(settings)/settings/(workspace)/layout.tsx", [
          route(
            ":workspaceSlug/settings/workload",
            "./(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/page.tsx"
          ),
        ]),
      ]),
    ]),
  ]),
];
