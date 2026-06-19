# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P2 — AI auto-create / triage endpoint.
# POST /api/ai/<slug>/projects/<project_id>/auto-create/ → 202.

import hashlib

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.ai_ext.gate import gate_or_403


class AiAutoCreateView(BaseAPIView):
    """Enqueue an AI triage task from freeform intake text.

    Returns 202 immediately; the `ai` queue worker produces the Issue +
    IntakeIssue asynchronously. Idempotent — duplicate submissions with
    the same text + project are coalesced via Redis lock in the task.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id):
        # H1 FIX: resolve project first, then gate using the confirmed workspace_id.
        # The old code tried request.parser_context["kwargs"].get("workspace_id") which
        # is never set by our URL patterns, so it always fell back to a slug lookup that
        # could return "" on DoesNotExist → gate_or_403("") → 500.
        from plane.db.models import Project, ProjectMember
        try:
            project = Project.objects.select_related("workspace").get(
                pk=project_id,
                workspace__slug=slug,
            )
        except Project.DoesNotExist:
            return Response({"error": "project not found"}, status=status.HTTP_404_NOT_FOUND)

        # Gate uses the resolved workspace_id from the project — never a derived/cached value.
        err = gate_or_403(str(project.workspace_id))
        if err:
            return err

        # H2 FIX: allow_permission default is workspace-scoped, meaning ANY active workspace
        # member passes the decorator.  Add an explicit active-ProjectMember check to confirm
        # the calling user actually belongs to THIS project (not just the workspace).
        is_project_member = ProjectMember.objects.filter(
            project_id=project_id,
            member=request.user,
            is_active=True,
            workspace__slug=slug,
        ).exists()
        if not is_project_member:
            return Response(
                {"error": "You are not an active member of this project."},
                status=status.HTTP_403_FORBIDDEN,
            )

        source_text = request.data.get("text", "").strip()
        if not source_text:
            return Response(
                {"error": "text is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from plane.ai_ext.bgtasks.triage_task import ai_triage_issue

        ai_triage_issue.apply_async(
            kwargs={
                "workspace_id": str(project.workspace_id),
                "project_id": str(project_id),
                "source_text": source_text,
                "created_by_id": str(request.user.id),
            },
            queue="ai",
        )

        return Response(
            {"status": "queued", "message": "AI triage request accepted"},
            status=status.HTTP_202_ACCEPTED,
        )


class AiIntakeDraftView(BaseAPIView):
    """Read the AI-generated draft from an IntakeIssue's extra field.

    Core IntakeIssueSerializer does not expose extra — this endpoint
    fills that gap for the ai-ext frontend modal.
    GET /api/ai/<slug>/projects/<project_id>/intake-draft/<intake_issue_id>/
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, intake_issue_id):
        from plane.db.models import IntakeIssue, ProjectMember

        try:
            intake_issue = IntakeIssue.objects.select_related("issue").get(
                pk=intake_issue_id,
                project_id=project_id,
                workspace__slug=slug,
                source="AI",
            )
        except IntakeIssue.DoesNotExist:
            return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

        # Guest narrowing: guests with restricted access can only see own issues.
        member = ProjectMember.objects.filter(
            project_id=project_id,
            member=request.user,
            is_active=True,
            workspace__slug=slug,
        ).first()
        if member and member.role == ROLE.GUEST.value:
            from plane.db.models import Project
            project = Project.objects.get(pk=project_id)
            if not project.guest_view_all_features:
                if intake_issue.issue.created_by_id != request.user.id:
                    return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "intake_issue_id": str(intake_issue.id),
                "issue_id": str(intake_issue.issue_id),
                "draft": intake_issue.extra,
                "confidence": intake_issue.extra.get("confidence"),
                "model": intake_issue.extra.get("model"),
            },
            status=status.HTTP_200_OK,
        )


# (H1 fix removed _workspace_id_from_slug — workspace_id is now always taken
#  from the resolved project.workspace_id, never from a slug-derived fallback.)
