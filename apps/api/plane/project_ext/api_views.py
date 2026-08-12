# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) project visibility endpoints — API-key authenticated,
# for MCP / SDK / external consumers.
#
# WHY THIS EXISTS: `Project.network` (0 = secret/private, 2 = public) is a core
# column, but it is not listed in
# `plane.api.serializers.project.ProjectCreateSerializer.Meta.fields`, so DRF
# silently drops it on /api/v1/ create AND update. A PATCH with {"network": 0}
# returns 200 OK with network unchanged — a successful-looking no-op. The core
# serializer is not a docs/FORK.md touch-point, so we expose the field from this
# fork-owned app instead of editing core.

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView  # APIKeyAuthentication
from plane.app.permissions import ROLE, allow_permission

from .service import (
    parse_network,
    resolve_project_or_404,
    serialize,
    set_visibility,
    set_visibility_bulk,
)


class ProjectVisibilityAPIEndpoint(BaseAPIView):
    """GET/PATCH /api/v1/workspaces/<slug>/projects/<project_id>/visibility/

    GET — any workspace member. PATCH — workspace admin, body {"network": 0|2}.
    <slug> MUST own <project_id> (404 otherwise, checked before the role gate).
    """

    def initial(self, request, *args, **kwargs):
        self._project = resolve_project_or_404(kwargs.get("slug"), kwargs.get("project_id"))
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, project_id):
        return Response(serialize(self._project), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, project_id):
        network, error = parse_network(request.data.get("network"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(set_visibility(self._project, network), status=status.HTTP_200_OK)


class ProjectVisibilityBulkAPIEndpoint(BaseAPIView):
    """PATCH /api/v1/workspaces/<slug>/project-visibility/

    Workspace admin only. Body: {"project_ids": [...], "network": 0|2}.
    All ids must resolve inside <slug> — one unknown id fails the whole call
    rather than applying a partial update.
    """

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug):
        network, error = parse_network(request.data.get("network"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        payload, error = set_visibility_bulk(slug, request.data.get("project_ids"), network)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(payload, status=status.HTTP_200_OK)
