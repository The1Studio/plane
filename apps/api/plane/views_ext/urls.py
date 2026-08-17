# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# App-API (/api/views-ext/) routes — mounted from core urls.py via an append-only
# include (docs/FORK.md touch-point 2).
#
#   GET /api/views-ext/workspaces/<slug>/issues/

from django.urls import path

from .views import GroupedWorkspaceViewIssuesEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/issues/",
        GroupedWorkspaceViewIssuesEndpoint.as_view(),
        name="views-ext-workspace-issues",
    ),
]
