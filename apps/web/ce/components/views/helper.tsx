/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { IProjectView } from "@plane/types";
import { EIssueLayoutTypes } from "@plane/types";
// The1Studio fork (views-layouts)
import { GLOBAL_VIEW_LAYOUTS } from "@plane/views-ext";
import { LayoutSelection } from "@/components/issues/issue-layouts/filters/header/layout-selection";
import { WorkspaceKanBanRoot } from "@/components/issues/issue-layouts/kanban/roots/workspace-root";
import { WorkspaceListRoot } from "@/components/issues/issue-layouts/list/roots/workspace-root";
import type { TWorkspaceLayoutProps } from "@/components/views/helper";

export type TLayoutSelectionProps = {
  onChange: (layout: EIssueLayoutTypes) => void;
  selectedLayout: EIssueLayoutTypes;
  workspaceSlug: string;
};

/**
 * The1Studio fork (views-layouts) — upstream stubs these two exports to `<></>`, which is why the
 * Views tab shipped spreadsheet-only. Both are already mounted upstream (the header renders
 * GlobalViewLayoutSelection; core/components/views/helper.tsx falls through to
 * WorkspaceAdditionalLayouts), so filling them here is the whole UI integration.
 *
 * Keep these bodies as delegations only — this file is a permanent rebase-conflict surface, and
 * every line of logic belongs in @plane/views-ext or in the layout roots.
 */
export function GlobalViewLayoutSelection(props: TLayoutSelectionProps) {
  const { onChange, selectedLayout } = props;
  return <LayoutSelection layouts={GLOBAL_VIEW_LAYOUTS} onChange={onChange} selectedLayout={selectedLayout} />;
}

export function WorkspaceAdditionalLayouts(props: TWorkspaceLayoutProps) {
  switch (props.activeLayout) {
    case EIssueLayoutTypes.LIST:
      return <WorkspaceListRoot />;
    case EIssueLayoutTypes.KANBAN:
      return <WorkspaceKanBanRoot />;
    // Calendar and Timeline are added by later phases. An unhandled layout renders blank rather
    // than throwing, so a stale persisted display-filter cannot break the page.
    default:
      return <></>;
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function AdditionalHeaderItems(view: IProjectView) {
  return <></>;
}
