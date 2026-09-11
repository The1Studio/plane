# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) workspace_ext routes — mounted from core urls.py via an
# append-only include (docs/FORK.md touch-point 2), BEFORE plane.api.urls so
# this path resolves first (mirrors plane.workload.api_urls).
#
#   POST /api/v1/workspaces/            (instance admin only)
#   GET  /api/v1/users/me/workspaces/
#
# NOTE on shadowing: core registers `users/me/` in plane.api.urls.user, and this
# app's urls are included BEFORE plane.api.urls. `users/me/workspaces/` is a
# distinct exact path, so it does NOT shadow core's endpoint — Django matches
# the full path, and `users/me/` still resolves to core's UserEndpoint. Do not
# register a bare `users/me/` here; that WOULD silently shadow a working core
# endpoint for every API consumer (see the same caution in
# plane/project_ext/api_urls.py).
#
# The same caution applies to `workspaces/`: core has no bare collection route
# at /api/v1/workspaces/ (every v1 workspace route is `workspaces/<slug>/...`),
# so this path shadows nothing. A future core route at that exact path WOULD be
# shadowed, and this is the line to re-check when upstream adds one.

from django.urls import path

from .api_views import UserWorkspacesAPIEndpoint, WorkspaceCreateAPIEndpoint

urlpatterns = [
    path(
        "workspaces/",
        WorkspaceCreateAPIEndpoint.as_view(http_method_names=["post"]),
        name="api-workspace-create",
    ),
    path(
        "users/me/workspaces/",
        UserWorkspacesAPIEndpoint.as_view(http_method_names=["get"]),
        name="api-user-workspaces",
    ),
]
