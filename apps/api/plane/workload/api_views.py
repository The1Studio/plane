# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) workload endpoints — API-key authenticated, for MCP /
# SDK / external consumers. Same access control (@allow_permission) and shared
# handlers as the app-API views (views.py); only the auth class differs.

from plane.api.views.base import BaseAPIView  # APIKeyAuthentication
from plane.app.permissions import ROLE, allow_permission

from .views import _run, estimate_delete, estimate_get, estimate_put


class WorkspaceWorkloadAPIEndpoint(BaseAPIView):
    """GET /api/v1/workspaces/<slug>/workload/"""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return _run(request, slug, route_project_id=None)


class ProjectWorkloadAPIEndpoint(BaseAPIView):
    """GET /api/v1/workspaces/<slug>/projects/<project_id>/workload/"""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        return _run(request, slug, route_project_id=project_id)


class WorkloadEstimateAPIEndpoint(BaseAPIView):
    """GET/PUT/DELETE /api/v1/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/workload-estimate/"""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        return estimate_get(request, slug, project_id, issue_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        return estimate_put(request, slug, project_id, issue_id)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, issue_id):
        return estimate_delete(project_id, issue_id)
