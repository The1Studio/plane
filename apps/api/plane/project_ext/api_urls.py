# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) project_ext routes — mounted from core urls.py via an
# append-only include (docs/FORK.md touch-point 2), BEFORE plane.api.urls so
# these paths resolve first (mirrors plane.workload.api_urls).
#
#   GET/PATCH /api/v1/workspaces/<slug>/projects/<project_id>/visibility/
#   PATCH     /api/v1/workspaces/<slug>/project-visibility/
#   GET       /api/v1/workspaces/<slug>/all-projects/
#   POST      /api/v1/workspaces/<slug>/project-members/
#
# NOTE on the member-add path: NOT `.../projects/<project_id>/members/` —
# that path is already registered by core (plane.api.urls.member,
# name="project-members") and this app's urls are included BEFORE
# plane.api.urls, so reusing it would silently shadow the working core
# endpoint. `.../project-members/` (workspace-scoped, bulk, no
# `<project_id>` path segment) is the fork-owned, non-colliding path.

from django.urls import path

from .api_views import (
    ProjectAllListAPIEndpoint,
    ProjectMemberBulkAddAPIEndpoint,
    ProjectVisibilityAPIEndpoint,
    ProjectVisibilityBulkAPIEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/visibility/",
        ProjectVisibilityAPIEndpoint.as_view(),
        name="api-project-visibility",
    ),
    path(
        "workspaces/<str:slug>/project-visibility/",
        ProjectVisibilityBulkAPIEndpoint.as_view(),
        name="api-project-visibility-bulk",
    ),
    path(
        "workspaces/<str:slug>/all-projects/",
        ProjectAllListAPIEndpoint.as_view(),
        name="api-project-all-list",
    ),
    path(
        "workspaces/<str:slug>/project-members/",
        ProjectMemberBulkAddAPIEndpoint.as_view(),
        name="api-project-members-bulk-add",
    ),
]
