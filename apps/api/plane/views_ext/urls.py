# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# App-API (/api/views-ext/) routes — mounted from core urls.py via an append-only
# include (docs/FORK.md touch-point 2).
#
#   GET /api/views-ext/workspaces/<slug>/issues/
#   GET /api/views-ext/workspaces/<slug>/user-issues/<user_id>/

from django.urls import path

from .views import (
    GroupedWorkspaceUserProfileIssuesEndpoint,
    GroupedWorkspaceViewIssuesEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/issues/",
        GroupedWorkspaceViewIssuesEndpoint.as_view(),
        name="views-ext-workspace-issues",
    ),
    path(
        "workspaces/<str:slug>/user-issues/<uuid:user_id>/",
        GroupedWorkspaceUserProfileIssuesEndpoint.as_view(),
        name="views-ext-workspace-user-profile-issues",
    ),
]
