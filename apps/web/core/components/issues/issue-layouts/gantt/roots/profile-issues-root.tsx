/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// The1Studio fork (profile-layouts)
// PROFILE-store Timeline sibling of `../../list/roots/profile-issues-root.tsx`
// (`ProfileIssuesListLayout`) and `../../kanban/roots/profile-issues-root.tsx`
// (`ProfileIssuesKanBanLayout`) — see either file for the full set. NEW file: no upstream
// Timeline layout existed for the profile "Your work" pages.
//
// Unlike List/Kanban/Calendar/Spreadsheet, `BaseGanttRoot` takes no `QuickActions` /
// `canEditPropertiesBasedOnProject` props, so this root only needs `viewId` — the same shape as
// `../../gantt/roots/workspace-root.tsx` (`WorkspaceGanttRoot`), which this file mirrors for the
// PROFILE store. See `base-gantt-root.tsx`'s `GanttStoreType` union + `updateBlockDates` for the
// workspace-level date-drag fallback this store type now shares with GLOBAL.

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// local imports
import { BaseGanttRoot } from "../base-gantt-root";

export const ProfileIssuesGanttLayout = observer(function ProfileIssuesGanttLayout() {
  // router
  const { profileViewId } = useParams();

  return <BaseGanttRoot viewId={profileViewId?.toString()} />;
});
