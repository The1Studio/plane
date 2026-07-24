# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) github_ext routes — mounted from core urls.py via an
# append-only include (docs/FORK.md touch-point 2), BEFORE plane.api.urls so
# these paths resolve first (mirrors plane.workload.api_urls).
#
# Naming follows the public-API `workspaces/<slug>/...` convention (not the
# internal `/api/github/...` shape) — a single "github-config" resource name
# reused across all three tiers:
#
#   GET/PUT /api/v1/github-config/                                            (instance admin)
#   GET/PUT /api/v1/workspaces/<slug>/github-config/                          (ws member GET / ws admin PUT)
#   GET/PUT /api/v1/workspaces/<slug>/projects/<project_id>/github-config/    (ws member GET / ws admin PUT)

from django.urls import path

from .api_views import (
    GithubGlobalConfigAPIEndpoint,
    GithubProjectConfigAPIEndpoint,
    GithubWorkspaceConfigAPIEndpoint,
)

urlpatterns = [
    path(
        "github-config/",
        GithubGlobalConfigAPIEndpoint.as_view(),
        name="api-github-global-config",
    ),
    path(
        "workspaces/<str:slug>/github-config/",
        GithubWorkspaceConfigAPIEndpoint.as_view(),
        name="api-github-workspace-config",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/github-config/",
        GithubProjectConfigAPIEndpoint.as_view(),
        name="api-github-project-config",
    ),
]
