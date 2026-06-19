# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# ai_ext URL routes (SP2). Mounted at /api/ai/ from the core urls.py
# (append-only include — docs/FORK.md touch-point 2).

from django.urls import path

from plane.ai_ext.views.config import AiWorkspaceConfigView
from plane.ai_ext.views.search import AiSearchView
from plane.ai_ext.views.triage import AiAutoCreateView, AiIntakeDraftView

urlpatterns = [
    # Workspace AI config (enable, ceiling, egress ack, kill-switch).
    path(
        "<str:slug>/config/",
        AiWorkspaceConfigView.as_view(),
        name="ai-workspace-config",
    ),
    # RAG semantic search + generation.
    path(
        "<str:slug>/search/",
        AiSearchView.as_view(),
        name="ai-search",
    ),
    # AI auto-create / triage: accept intake text → 202.
    path(
        "<str:slug>/projects/<uuid:project_id>/auto-create/",
        AiAutoCreateView.as_view(),
        name="ai-auto-create",
    ),
    # Read the AI-generated draft from an IntakeIssue.
    path(
        "<str:slug>/projects/<uuid:project_id>/intake-draft/<uuid:intake_issue_id>/",
        AiIntakeDraftView.as_view(),
        name="ai-intake-draft",
    ),
]
