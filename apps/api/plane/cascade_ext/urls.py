# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Mounted at /api/cascade-ext/ from core urls.py via an append-only include
# (docs/FORK.md touch-point 2).
#
#   GET  /api/cascade-ext/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/cascade-preview/
#   POST /api/cascade-ext/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/cascade-apply/

from django.urls import path

from .views import CascadeApplyEndpoint, CascadePreviewEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/cascade-preview/",
        CascadePreviewEndpoint.as_view(),
        name="cascade-ext-preview",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/cascade-apply/",
        CascadeApplyEndpoint.as_view(),
        name="cascade-ext-apply",
    ),
]
