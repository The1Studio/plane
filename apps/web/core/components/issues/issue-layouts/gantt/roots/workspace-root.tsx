/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// The1Studio fork (views-layouts)
// GLOBAL-store Timeline sibling of `../../list/roots/workspace-root.tsx` (`WorkspaceListRoot`)
// and `../../kanban/roots/workspace-root.tsx` (`WorkspaceKanBanRoot`) — see either file's roots/
// directory for the full set. NEW file: no upstream equivalent for a cross-project Timeline.
//
// Unlike List/Kanban, `BaseGanttRoot` takes no `QuickActions` / `canEditPropertiesBasedOnProject`
// props, so this root only needs to pass `viewId` — the same shape as the project-view template
// this component is modelled on (`../../roots/project-view-layout-root.tsx:37`,
// `<BaseGanttRoot viewId={…} />`). No `IssuesStoreContext.Provider` wrap is needed either: on
// `/workspace-views/:globalViewId`, `useIssueStoreType()` (called inside `BaseGanttRoot`) resolves
// to `EIssuesStoreType.GLOBAL` from the `globalViewId` route param alone. See plan.md § B3/D5 and
// `base-gantt-root.tsx`'s `GanttStoreType` union + `updateBlockDates` for the date-drag fallback
// this store type needs.

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// local imports
import { BaseGanttRoot } from "../base-gantt-root";

export const WorkspaceGanttRoot = observer(function WorkspaceGanttRoot() {
  // router
  const { globalViewId } = useParams();

  return <BaseGanttRoot viewId={globalViewId?.toString()} />;
});
