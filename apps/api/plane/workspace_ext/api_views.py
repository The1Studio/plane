# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) workspace discovery — API-key authenticated, for MCP /
# SDK / external consumers.
#
# WHY THIS EXISTS: every workspace-scoped route in the public API takes the
# workspace slug as a path segment (/api/v1/workspaces/<slug>/...), but no v1
# route returns the slugs a caller can access. An API-key client therefore
# cannot bootstrap itself — the slug has to be supplied out-of-band by a human
# reading it out of the browser address bar.
#
# Guessing is not a fallback: an unknown slug and a real workspace the caller
# cannot access both answer 403 with byte-identical bodies
# ({"detail":"You do not have permission to perform this action."}), so the
# value can be neither listed nor probed. A 23-candidate sweep against our own
# instance could not distinguish a hit from a miss.
#
# The web app's internal API does expose /api/users/me/workspaces/, but it is
# session-cookie authenticated and rejects API keys in every header form, so it
# is unreachable for the clients that need this.
#
# Nothing structural was in the way: APIKeyAuthentication resolves to the USER
# (api_token.user), APIToken.workspace is a nullable FK, and core's own
# /api/v1/users/me/ already proves a non-workspace-scoped v1 endpoint works with
# an API key. This app wires those facts together without touching core —
# `plane.api.views.user` and `plane.api.urls.user` are NOT docs/FORK.md
# touch-points, so the endpoint lives here instead.

from rest_framework import status
from rest_framework.response import Response

from plane.api.serializers import WorkspaceLiteSerializer
from plane.api.views.base import BaseAPIView  # APIKeyAuthentication
from plane.db.models import Workspace


class UserWorkspacesAPIEndpoint(BaseAPIView):
    """List the workspaces the authenticated user is an active member of.

    Grants no new access: it returns only workspaces the caller already belongs
    to, and every workspace-scoped route still enforces its own permissions. It
    makes the identifier those routes require discoverable by the client that
    needs it.
    """

    serializer_class = WorkspaceLiteSerializer
    model = Workspace

    def get(self, request):
        # Mirrors the membership filter core's internal API already uses
        # (plane/app/views/workspace/base.py). `is_active` is load-bearing: a
        # deactivated membership must not resurface a workspace the caller can
        # no longer reach, because every subsequent call with that slug would
        # 403 — handing it back is actively misleading, not merely redundant.
        workspaces = (
            Workspace.objects.filter(
                workspace_member__member=request.user,
                workspace_member__is_active=True,
            )
            .distinct()
            .order_by("name")
        )
        serializer = WorkspaceLiteSerializer(workspaces, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
