/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// The1Studio fork (profile-layouts)
// PROFILE-store Calendar sibling of `../../list/roots/profile-issues-root.tsx`
// (`ProfileIssuesListLayout`) and `../../kanban/roots/profile-issues-root.tsx`
// (`ProfileIssuesKanBanLayout`) — see either file for the full set. NEW file: no upstream
// Calendar layout existed for the profile "Your work" pages.
//
// Quick-add is a non-issue here, doubly so vs. the GLOBAL-store Calendar
// (`calendar/roots/workspace-root.tsx`): `IProfileIssues.quickAddIssue` is `undefined` at the
// store level (`store/issue/profile/issue.store.ts`) and `useProfileIssueActions` never returns
// a `quickAddIssue` key at all, so `quickAddCallback` below is `undefined` regardless of the
// `calendar.tsx:112-114` hardcoded-PROJECT-viewFlags quirk that protects the GLOBAL store. The
// `calendar/quick-add-issue-actions.tsx:82` `!projectId` null guard is a second, independent
// backstop — `/profile/:userId/assigned` has no `:projectId` route param either.

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { ProjectIssueQuickActions } from "../../quick-action-dropdowns";
import { BaseCalendarRoot } from "../base-calendar-root";

export const ProfileIssuesCalendarLayout = observer(function ProfileIssuesCalendarLayout() {
  // router
  const { workspaceSlug, profileViewId } = useParams();
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
    <BaseCalendarRoot
      QuickActions={ProjectIssueQuickActions}
      canEditPropertiesBasedOnProject={canEditPropertiesBasedOnProject}
      viewId={profileViewId?.toString()}
    />
  );
});
