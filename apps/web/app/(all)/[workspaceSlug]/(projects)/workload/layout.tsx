// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline) — route layout for the Workload tab.
//
// Every other workspace-level page in core wraps its page in a layout that
// renders `<AppHeader>` (compare active-cycles/layout.tsx). The Workload route
// went straight to its page component, which meant it never mounted an
// AppHeader — and since `ExtendedAppHeader` is what renders
// `AppSidebarToggleButton` when the app sidebar is collapsed, collapsing the
// sidebar on this tab left NO WAY TO REOPEN IT. Adopting the same layout shape
// fixes that and gives the tab the breadcrumb every sibling page has.

import { Outlet } from "react-router";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { WorkloadHeader } from "./header";

export default function WorkloadLayout() {
  return (
    <>
      <AppHeader header={<WorkloadHeader />} />
      <ContentWrapper>
        <Outlet />
      </ContentWrapper>
    </>
  );
}
