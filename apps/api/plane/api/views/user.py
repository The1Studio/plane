# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiResponse

# Module imports
from plane.api.serializers import UserLiteSerializer, WorkspaceLiteSerializer
from plane.api.views.base import BaseAPIView
from plane.db.models import User, Workspace
from plane.utils.openapi.decorators import user_docs
from plane.utils.openapi import USER_EXAMPLE


class UserEndpoint(BaseAPIView):
    serializer_class = UserLiteSerializer
    model = User

    @user_docs(
        operation_id="get_current_user",
        summary="Get current user",
        description="Retrieve the authenticated user's profile information including basic details.",
        responses={
            200: OpenApiResponse(
                description="Current user profile",
                response=UserLiteSerializer,
                examples=[USER_EXAMPLE],
            ),
        },
    )
    def get(self, request):
        """Get current user

        Retrieve the authenticated user's profile information including basic details.
        Returns user data based on the current authentication context.
        """
        serializer = UserLiteSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserWorkspacesEndpoint(BaseAPIView):
    """List the workspaces the authenticated user belongs to.

    Every other v1 route is workspace-scoped and takes the slug as a path
    segment, but until this endpoint existed no v1 route returned those slugs --
    so an API-key client could not bootstrap itself. Guessing was not a fallback
    either: an unknown slug and a real workspace the caller cannot access both
    answer `403` with identical bodies, so the value could be neither listed nor
    probed (see issue #29).

    This grants no new access. It returns only workspaces the caller is already
    an active member of, and every workspace-scoped route still enforces its own
    permissions -- it just makes the identifier those routes require
    discoverable by the client that needs it.
    """

    serializer_class = WorkspaceLiteSerializer
    model = Workspace

    @user_docs(
        operation_id="list_user_workspaces",
        summary="List current user's workspaces",
        description=(
            "Retrieve the workspaces the authenticated user is an active member of. "
            "Use this to discover the workspace slug required by every other endpoint."
        ),
        responses={
            200: OpenApiResponse(
                description="Workspaces the current user belongs to",
                response=WorkspaceLiteSerializer(many=True),
            ),
        },
    )
    def get(self, request):
        """List current user's workspaces

        Retrieve the workspaces the authenticated user is an active member of.
        """
        # Mirrors the membership filter the internal API already uses
        # (plane/app/views/workspace/base.py). `is_active` matters: a
        # deactivated membership must not resurface a workspace the user can no
        # longer reach, which would hand back a slug that 403s on every
        # subsequent call.
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
