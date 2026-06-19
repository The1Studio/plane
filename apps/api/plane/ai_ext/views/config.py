# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 — Workspace AI config CRUD (enable/disable gate, kill-switch).
# PATCH /api/ai/<slug>/config/ — admin only.

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView


class AiWorkspaceConfigView(BaseAPIView):
    """Read + update the AI config for a workspace.

    GET  /api/ai/<slug>/config/ — any member
    PATCH /api/ai/<slug>/config/ — admin only
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug):
        from plane.ai_ext.models import AiWorkspaceConfig
        from plane.db.models import Workspace

        try:
            workspace = Workspace.objects.get(slug=slug)
        except Workspace.DoesNotExist:
            return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

        config, _ = AiWorkspaceConfig.get_or_create_for(workspace.id)
        return Response(
            {
                "enabled": config.enabled,
                "monthly_usd_ceiling": config.monthly_usd_ceiling,
                "egress_acked_at": config.egress_acked_at,
            },
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug):
        from plane.ai_ext.models import AiWorkspaceConfig
        from plane.db.models import Workspace
        from plane.ai_ext.bgtasks.embed_task import purge_workspace_embeddings
        from django.utils import timezone

        try:
            workspace = Workspace.objects.get(slug=slug)
        except Workspace.DoesNotExist:
            return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

        config, _ = AiWorkspaceConfig.get_or_create_for(workspace.id)

        was_enabled = config.enabled

        if "enabled" in request.data:
            config.enabled = bool(request.data["enabled"])
        if "monthly_usd_ceiling" in request.data:
            config.monthly_usd_ceiling = float(request.data["monthly_usd_ceiling"])
        if "egress_acked" in request.data and request.data["egress_acked"]:
            config.egress_acked_by = request.user
            config.egress_acked_at = timezone.now()

        config.save()

        # Kill-switch: disabling a workspace purges its embeddings.
        if was_enabled and not config.enabled:
            purge_workspace_embeddings.apply_async(
                kwargs={"workspace_id": str(workspace.id)},
                queue="ai",
            )

        return Response(
            {"enabled": config.enabled, "monthly_usd_ceiling": config.monthly_usd_ceiling},
            status=status.HTTP_200_OK,
        )
