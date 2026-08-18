/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (workspace work settings) — new file.
 * Header for the workspace-wide work-settings page. This tab does not exist
 * in the sealed `@plane/constants` WORKSPACE_SETTINGS registry (docs/FORK.md
 * "Frontend core-edit exceptions"), so — unlike the core headers this mirrors
 * (e.g. exports/header.tsx) — the label and icon are supplied directly here
 * rather than looked up via `WORKSPACE_SETTINGS.workload` / `WORKSPACE_SETTINGS_ICONS`.
 */

import { Clock } from "lucide-react";
import { Breadcrumbs } from "@plane/ui";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { SettingsPageHeader } from "@/components/settings/page-header";

export function WorkloadWorkSettingsHeader() {
  return (
    <SettingsPageHeader
      leftItem={
        <div className="flex items-center gap-2">
          <Breadcrumbs>
            <Breadcrumbs.Item
              component={<BreadcrumbLink label="Work settings" icon={<Clock className="size-4 text-tertiary" />} />}
            />
          </Breadcrumbs>
        </div>
      }
    />
  );
}
