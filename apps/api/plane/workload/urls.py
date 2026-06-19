# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Mounted at /api/ from core urls.py (append-only include — FORK.md touch-point 2).

from django.urls import path

from .views import (
    ProjectWorkloadEndpoint,
    WorkloadEstimateEndpoint,
    WorkspaceWorkloadEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/workload/",
        WorkspaceWorkloadEndpoint.as_view(),
        name="workspace-workload",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/workload/",
        ProjectWorkloadEndpoint.as_view(),
        name="project-workload",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/workload-estimate/",
        WorkloadEstimateEndpoint.as_view(),
        name="workload-estimate",
    ),
]
