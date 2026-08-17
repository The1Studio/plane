/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// The1Studio fork (views-layouts)
// GLOBAL-store List sibling of `../../spreadsheet/roots/workspace-root.tsx`
// (`WorkspaceSpreadsheetRoot`) — see that file's roots/ directory for the full set.
// NEW file: no upstream equivalent for a cross-project List layout.

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { AllIssueQuickActions } from "../../quick-action-dropdowns";
import { BaseListRoot } from "../base-list-root";

export const WorkspaceListRoot = observer(function WorkspaceListRoot() {
  // router
  const { workspaceSlug, globalViewId } = useParams();
  // store
  const { allowPermissions } = useUserPermissions();

  const canEditPropertiesBasedOnProject = (projectId: string) =>
    allowPermissions(
      [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
      EUserPermissionsLevel.PROJECT,
      workspaceSlug.toString(),
      projectId
    );

  return (
    <BaseListRoot
      QuickActions={AllIssueQuickActions}
      canEditPropertiesBasedOnProject={canEditPropertiesBasedOnProject}
      viewId={globalViewId?.toString()}
    />
  );
});
