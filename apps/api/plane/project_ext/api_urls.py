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

from django.urls import path

from .api_views import (
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
]
