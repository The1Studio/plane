# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) workload routes — mounted from core urls.py via an
# append-only include (docs/FORK.md touch-point 2).

from django.urls import path

from .api_views import (
    ProjectWorkloadAPIEndpoint,
    WorkloadEstimateAPIEndpoint,
    WorkloadEstimatesBulkAPIEndpoint,
    WorkloadRollupsBulkAPIEndpoint,
    WorkspaceWorkloadAPIEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/workload/",
        WorkspaceWorkloadAPIEndpoint.as_view(),
        name="api-workspace-workload",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/workload/",
        ProjectWorkloadAPIEndpoint.as_view(),
        name="api-project-workload",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/workload-estimate/",
        WorkloadEstimateAPIEndpoint.as_view(),
        name="api-workload-estimate",
    ),
    path(
        "workspaces/<str:slug>/workload-estimates/",
        WorkloadEstimatesBulkAPIEndpoint.as_view(),
        name="api-workload-estimates-bulk",
    ),
    path(
        "workspaces/<str:slug>/workload-rollups/",
        WorkloadRollupsBulkAPIEndpoint.as_view(),
        name="api-workload-rollups-bulk",
    ),
]
