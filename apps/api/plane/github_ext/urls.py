# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# github_ext URL routes (P0). Mounted at /api/ from the core urls.py
# (append-only include — docs/FORK.md touch-point 2), so this resolves to
# POST /api/github/webhook/.

from django.urls import path

from plane.github_ext.views.config import (
    GithubGlobalConfigView,
    GithubProjectConfigView,
    GithubWorkspaceConfigView,
)
from plane.github_ext.webhook.views import GithubWebhookView

urlpatterns = [
    path("github/webhook/", GithubWebhookView.as_view(), name="github-webhook"),
    # P2/P4 — status-automation config CRUD, three-tier scoping
    # (views/config.py): instance-global -> per-workspace -> per-project.
    path(
        "github/config/",
        GithubGlobalConfigView.as_view(),
        name="github-global-config",
    ),
    path(
        "github/<str:slug>/config/",
        GithubWorkspaceConfigView.as_view(),
        name="github-workspace-config",
    ),
    path(
        "github/<str:slug>/projects/<uuid:project_id>/config/",
        GithubProjectConfigView.as_view(),
        name="github-project-config",
    ),
]
