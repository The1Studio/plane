# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# github_ext URL routes (P0). Mounted at /api/ from the core urls.py
# (append-only include — docs/FORK.md touch-point 2), so this resolves to
# POST /api/github/webhook/.

from django.urls import path

from plane.github_ext.webhook.views import GithubWebhookView

urlpatterns = [
    path("github/webhook/", GithubWebhookView.as_view(), name="github-webhook"),
]
