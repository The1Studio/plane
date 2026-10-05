# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) project-page routes — mounted from core urls.py via an
# append-only include (docs/FORK.md touch-point 2), BEFORE plane.api.urls (core
# registers no v1 page route at all: an unmatched path falls through to the
# custom 404 handler, {"error": "Page not found."}).
#
#   GET        /api/v1/workspaces/<slug>/projects/<project_id>/pages/
#   GET/PATCH  /api/v1/workspaces/<slug>/projects/<project_id>/pages/<page_id>/

from django.urls import path

from .api_views import PageDetailAPIEndpoint, PageListAPIEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/",
        PageListAPIEndpoint.as_view(),
        name="api-page-list",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/",
        PageDetailAPIEndpoint.as_view(),
        name="api-page-detail",
    ),
]
