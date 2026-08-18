/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Clock } from "lucide-react";
import { observer } from "mobx-react";
import { usePathname } from "next/navigation";
import { useParams } from "react-router";
// plane imports
import {
  EUserPermissions,
  EUserPermissionsLevel,
  GROUPED_WORKSPACE_SETTINGS,
  WORKSPACE_SETTINGS_CATEGORIES,
  WORKSPACE_SETTINGS_CATEGORY,
} from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { joinUrlPath } from "@plane/utils";
// components
import { SettingsSidebarItem } from "@/components/settings/sidebar/item";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { WORKSPACE_SETTINGS_ICONS } from "./item-icon";

// The1Studio fork (workspace work settings) — the "Work settings" tab does
// not exist in the sealed @plane/constants WORKSPACE_SETTINGS registry
// (packages/constants/src/settings/workspace.ts is not edited in place;
// docs/FORK.md "Frontend core-edit exceptions"), so it cannot be added to
// GROUPED_WORKSPACE_SETTINGS / WORKSPACE_SETTINGS_ICONS. It is rendered
// directly below, ADMIN-only (the page writes; plan.md D2), fenced here.
const WORK_SETTINGS_HREF = "/settings/workload";

export const WorkspaceSettingsSidebarItemCategories = observer(function WorkspaceSettingsSidebarItemCategories() {
  // params
  const { workspaceSlug } = useParams();
  const pathname = usePathname();
  // store hooks
  const { allowPermissions } = useUserPermissions();
  // translation
  const { t } = useTranslation();

  return (
    <div className="mt-3 flex flex-col divide-y divide-subtle px-3">
      {WORKSPACE_SETTINGS_CATEGORIES.map((category) => {
        const categoryItems = GROUPED_WORKSPACE_SETTINGS[category];
        const accessibleItems = categoryItems.filter((item) =>
          allowPermissions(item.access, EUserPermissionsLevel.WORKSPACE, workspaceSlug)
        );

        // The1Studio fork (workspace work settings) — appended to the FEATURES
        // category only, and only for workspace admins (the page is ADMIN-only).
        // GROUPED_WORKSPACE_SETTINGS[FEATURES] is empty today (packages/constants
        // is sealed — see the module comment above), so `accessibleItems` alone
        // would always be 0 for this category and the early-return below would
        // hide it even when this item should show; the OR here is load-bearing.
        const showWorkSettingsItem =
          category === WORKSPACE_SETTINGS_CATEGORY.FEATURES &&
          allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE, workspaceSlug);

        if (accessibleItems.length === 0 && !showWorkSettingsItem) return null;

        return (
          <div key={category} className="shrink-0 py-3 first:pt-0 last:pb-0">
            <div className="p-2 text-caption-md-medium text-tertiary capitalize">{t(category)}</div>
            <div className="flex flex-col">
              {accessibleItems.map((item) => {
                const isItemActive =
                  item.href === "/settings"
                    ? pathname === `/${workspaceSlug}${item.href}/`
                    : new RegExp(`^/${workspaceSlug}${item.href}/`).test(pathname);

                return (
                  <SettingsSidebarItem
                    key={item.key}
                    as="link"
                    href={joinUrlPath(workspaceSlug ?? "", item.href)}
                    isActive={isItemActive}
                    icon={WORKSPACE_SETTINGS_ICONS[item.key]}
                    label={t(item.i18n_label)}
                  />
                );
              })}
              {showWorkSettingsItem && (
                <SettingsSidebarItem
                  key="workload"
                  as="link"
                  href={joinUrlPath(workspaceSlug ?? "", WORK_SETTINGS_HREF)}
                  isActive={new RegExp(`^/${workspaceSlug}${WORK_SETTINGS_HREF}/`).test(pathname)}
                  icon={Clock}
                  label="Work settings"
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
});
