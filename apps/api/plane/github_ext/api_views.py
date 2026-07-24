# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) mirror of the github_ext status-automation config CRUD
# (views/config.py) — API-key authenticated, for MCP / SDK / external
# consumers. Same three-tier scoping, same access control (@allow_permission /
# InstanceAdminPermission) and the same shared resolve/validate/persist
# handlers as the app-API views; only the auth class differs (mirrors
# workload/api_views.py's split from workload/views.py).

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView  # APIKeyAuthentication
from plane.app.permissions import ROLE, allow_permission
from plane.license.api.permissions import InstanceAdminPermission

from .views.config import (
    global_config_get,
    global_config_put,
    project_config_get,
    project_config_put,
    resolve_project_or_404,
    resolve_workspace_or_404,
    workspace_config_get,
    workspace_config_put,
)


class GithubGlobalConfigAPIEndpoint(BaseAPIView):
    """GET/PUT /api/v1/github-config/

    Public-API mirror of GithubGlobalConfigView. Instance admin only — the
    single scope="global" row is shared by every workspace on the instance.
    """

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        return Response({"rules": global_config_get()}, status=status.HTTP_200_OK)

    def put(self, request):
        rules, error = global_config_put(request.data.get("rules"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rules": rules}, status=status.HTTP_200_OK)


class GithubWorkspaceConfigAPIEndpoint(BaseAPIView):
    """GET/PUT /api/v1/workspaces/<slug>/github-config/

    Public-API mirror of GithubWorkspaceConfigView. GET — any workspace
    member; PUT ({"rules": {...}}) — workspace admin. Shape-only validation
    (a workspace override is project-agnostic).
    """

    def initial(self, request, *args, **kwargs):
        self._workspace = resolve_workspace_or_404(kwargs.get("slug"))
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return Response(
            {"rules": workspace_config_get(self._workspace)}, status=status.HTTP_200_OK
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        rules, error = workspace_config_put(self._workspace, request.data.get("rules"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rules": rules}, status=status.HTTP_200_OK)


class GithubProjectConfigAPIEndpoint(BaseAPIView):
    """GET/PUT /api/v1/workspaces/<slug>/projects/<project_id>/github-config/

    Public-API mirror of GithubProjectConfigView. GET — any workspace member;
    PUT — workspace admin, validating each state NAME exists in the project.
    <slug> MUST own <project_id> (404 otherwise, checked before the role gate).
    """

    def initial(self, request, *args, **kwargs):
        self._project = resolve_project_or_404(kwargs.get("slug"), kwargs.get("project_id"))
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, project_id):
        return Response(
            {"rules": project_config_get(self._project)}, status=status.HTTP_200_OK
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug, project_id):
        rules, error = project_config_put(self._project, request.data.get("rules"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rules": rules}, status=status.HTTP_200_OK)
