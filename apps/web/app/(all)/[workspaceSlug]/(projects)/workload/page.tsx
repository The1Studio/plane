// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// SP2 — Workload route page (apps/web route file).
// Imported by extended.ts; renders the @plane/workload-ext WorkloadMatrix.

"use client";
import { observer } from "mobx-react";
import { useParams } from "react-router";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { WorkloadMatrix } from "@plane/workload-ext";
import { PageHead } from "@/components/core/page-title";
import { useUserPermissions } from "@/hooks/store/user";
import { useWorkload } from "@/hooks/store/use-workload";

export default observer(function WorkloadPage() {
  const { workspaceSlug = "" } = useParams();
  const workloadStore = useWorkload();
  const { allowPermissions } = useUserPermissions();
  // Capacity editing is admin-only (docs/FORK.md workload-capacity plan D-B3); workspace-scoped.
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  // Fetch on mount (guarded against double-fetch and error states)
  if (!workloadStore.workloadData && !workloadStore.isLoading && !workloadStore.error) {
    workloadStore.fetchWorkload(workspaceSlug);
  }

  return (
    <>
      <PageHead title="Workload" />
      <div className="h-full overflow-y-auto px-6 py-4">
        <h1 className="text-xl mb-4 font-semibold">Workload</h1>
        <WorkloadMatrix store={workloadStore} workspaceSlug={workspaceSlug} isAdmin={isAdmin} />
      </div>
    </>
  );
});
