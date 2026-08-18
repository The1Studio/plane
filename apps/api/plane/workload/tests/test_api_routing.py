# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Proves the public-API (/api/v1/) workload routes resolve to OUR views and are
# not swallowed by plane.api.urls (our include is registered first). No DB.

import uuid

from django.test import SimpleTestCase
from django.urls import Resolver404, resolve

from plane.workload.api_views import (
    ProjectWorkloadAPIEndpoint,
    WorkloadEstimateAPIEndpoint,
    WorkloadRollupsBulkAPIEndpoint,
    WorkspaceWorkloadAPIEndpoint,
)


class TestPublicApiRouting(SimpleTestCase):
    def test_workspace_workload_route(self):
        match = resolve("/api/v1/workspaces/acme/workload/")
        self.assertEqual(match.func.view_class, WorkspaceWorkloadAPIEndpoint)

    def test_project_workload_route(self):
        pid = uuid.uuid4()
        match = resolve(f"/api/v1/workspaces/acme/projects/{pid}/workload/")
        self.assertEqual(match.func.view_class, ProjectWorkloadAPIEndpoint)

    def test_estimate_route(self):
        pid, iid = uuid.uuid4(), uuid.uuid4()
        match = resolve(
            f"/api/v1/workspaces/acme/projects/{pid}/issues/{iid}/workload-estimate/"
        )
        self.assertEqual(match.func.view_class, WorkloadEstimateAPIEndpoint)

    def test_rollups_bulk_route(self):
        match = resolve("/api/v1/workspaces/acme/workload-rollups/")
        self.assertEqual(match.func.view_class, WorkloadRollupsBulkAPIEndpoint)

    def test_capacity_route_is_gone(self):
        """Phase 3 (D1) deletes the per-member capacity endpoint entirely —
        the route must no longer resolve (not merely deny access)."""
        with self.assertRaises(Resolver404):
            resolve("/api/v1/workspaces/acme/workload-capacity/")
