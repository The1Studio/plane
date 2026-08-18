/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { usePathname } from "next/navigation";
import { Outlet } from "react-router";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { getWorkspaceActivePath, pathnameToAccessKey } from "@/components/settings/helper";
import { SettingsMobileNav } from "@/components/settings/mobile/nav";
// plane imports
import { WORKSPACE_SETTINGS_ACCESS } from "@plane/constants";
import { EUserWorkspaceRoles } from "@plane/types";
// components
import { WorkspaceSettingsSidebarRoot } from "@/components/settings/workspace/sidebar";
// hooks
import { useUserPermissions } from "@/hooks/store/user";

import type { Route } from "./+types/layout";

const WorkspaceSettingLayout = observer(function WorkspaceSettingLayout({ params }: Route.ComponentProps) {
  // router
  const { workspaceSlug } = params;
  // store hooks
  const { workspaceUserInfo, getWorkspaceRoleByWorkspaceSlug } = useUserPermissions();
  // next hooks
  const pathname = usePathname();
  // derived values
  const { accessKey } = pathnameToAccessKey(pathname);
  const userWorkspaceRole = getWorkspaceRoleByWorkspaceSlug(workspaceSlug);

  let isAuthorized: boolean | string = false;
  if (pathname && workspaceSlug && userWorkspaceRole) {
    isAuthorized = WORKSPACE_SETTINGS_ACCESS[accessKey]?.includes(userWorkspaceRole as EUserWorkspaceRoles);

    /* The1Studio fork (workspace work settings) */
    // WORKSPACE_SETTINGS_ACCESS is derived (href -> access) from WORKSPACE_SETTINGS
    // in the sealed @plane/constants package, so the fork's /settings/workload
    // route has no entry and the lookup above returns undefined -- which reads as
    // "not authorized" for EVERY role, including admins. The nav entry in
    // item-categories.tsx is ADMIN-gated; this mirrors that gate for the route
    // itself. It lives here rather than in @plane/constants because docs/FORK.md
    // forbids editing @plane/* packages in place.
    if (accessKey === "/settings/workload") {
      isAuthorized = userWorkspaceRole === EUserWorkspaceRoles.ADMIN;
    }
  }

  return (
    <>
      <SettingsMobileNav
        hamburgerContent={WorkspaceSettingsSidebarRoot}
        activePath={getWorkspaceActivePath(pathname) || ""}
      />
      <div className="inset-y-0 flex h-full w-full flex-row">
        {workspaceUserInfo && !isAuthorized ? (
          <NotAuthorizedView section="settings" className="h-auto" />
        ) : (
          <div className="relative flex size-full">
            <div className="hidden h-full md:block">
              <WorkspaceSettingsSidebarRoot />
            </div>
            <Outlet />
          </div>
        )}
      </div>
    </>
  );
});

export default WorkspaceSettingLayout;
