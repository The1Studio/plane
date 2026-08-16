# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) project visibility, workspace-admin project
# enumeration, and workspace-admin project-member-add endpoints — API-key
# authenticated, for MCP / SDK / external consumers.
#
# WHY THIS EXISTS: `Project.network` (0 = secret/private, 2 = public) is a core
# column, but it is not listed in
# `plane.api.serializers.project.ProjectCreateSerializer.Meta.fields`, so DRF
# silently drops it on /api/v1/ create AND update. A PATCH with {"network": 0}
# returns 200 OK with network unchanged — a successful-looking no-op. The core
# serializer is not a docs/FORK.md touch-point, so we expose the field from this
# fork-owned app instead of editing core.
#
# The all-projects and member-add endpoints below exist for a related reason:
# `plane.api.views.project.ProjectListCreateAPIEndpoint` only returns projects
# the caller is a project MEMBER of (plus public ones) — workspace ADMIN role
# is not enough, and there is no public-API endpoint to add a project member
# at all. Both gaps make "workspace admin enumerates + onboards a user across
# every project" impossible via the public API without this app.

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView  # APIKeyAuthentication
from plane.app.permissions import ROLE, allow_permission

from .service import (
    add_project_member,
    list_all_projects,
    parse_network,
    parse_role,
    resolve_project_or_404,
    resolve_target_user,
    resolve_workspace_or_404,
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


class ProjectAllListAPIEndpoint(BaseAPIView):
    """GET /api/v1/workspaces/<slug>/all-projects/

    Workspace admin only. Returns every project in the workspace, including
    private ones the caller is not a member of. <slug> unknown -> 404,
    resolved in initial() before the role gate (mirrors
    ProjectVisibilityAPIEndpoint.initial()); non-admin caller -> 403.
    """

    def initial(self, request, *args, **kwargs):
        self._workspace = resolve_workspace_or_404(kwargs.get("slug"))
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        return Response(list_all_projects(self._workspace, request.user.id), status=status.HTTP_200_OK)


class ProjectMemberAddAPIEndpoint(BaseAPIView):
    """POST /api/v1/workspaces/<slug>/projects/<project_id>/members/

    Workspace admin only. Body: {"user_id": "<uuid>"} OR {"email": "..."},
    plus optional {"role": 20|15|5} defaulting to 15 (Member). <slug> MUST own
    <project_id> (404 otherwise, checked before the role gate — mirrors
    ProjectVisibilityAPIEndpoint.initial()). The target user must already be
    an active member of the workspace (400 otherwise) — this endpoint adds a
    project member, never a workspace member.
    """

    def initial(self, request, *args, **kwargs):
        self._project = resolve_project_or_404(kwargs.get("slug"), kwargs.get("project_id"))
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, project_id):
        user, error = resolve_target_user(request.data.get("user_id"), request.data.get("email"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        role, error = parse_role(request.data.get("role"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        payload, error = add_project_member(slug, self._project, user, role)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(payload, status=status.HTTP_200_OK)
