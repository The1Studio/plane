# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) workspace routes — API-key authenticated, for MCP /
# SDK / external consumers.
#
# WHY THIS EXISTS: every workspace-scoped route in the public API takes the
# workspace slug as a path segment (/api/v1/workspaces/<slug>/...), but no v1
# route returns the slugs a caller can access, and no v1 route can MINT one.
# An API-key client therefore cannot bootstrap itself — the slug has to be
# supplied out-of-band by a human reading it out of the browser address bar,
# and the only way to make a new slug is the web UI (god-mode → Workspaces, or
# the onboarding flow).
#
# Guessing is not a fallback: an unknown slug and a real workspace the caller
# cannot access both answer 403 with byte-identical bodies
# ({"detail":"You do not have permission to perform this action."}), so the
# value can be neither listed nor probed. A 23-candidate sweep against our own
# instance could not distinguish a hit from a miss.
#
# The web app's internal API does expose /api/users/me/workspaces/ and
# POST /api/workspaces/, but it is session-cookie authenticated and rejects API
# keys in every header form, so it is unreachable for the clients that need
# this.
#
# Nothing structural was in the way: APIKeyAuthentication resolves to the USER
# (api_token.user), APIToken.workspace is a nullable FK, and core's own
# /api/v1/users/me/ already proves a non-workspace-scoped v1 endpoint works with
# an API key. This app wires those facts together without touching core —
# `plane.api.views.user` and `plane.api.urls.user` are NOT docs/FORK.md
# touch-points, so the endpoints live here instead.

# Python imports
import os

# Django imports
from django.db import IntegrityError, transaction

# Third party imports
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

# Module imports
from plane.api.serializers import WorkspaceLiteSerializer
from plane.api.views.base import BaseAPIView  # APIKeyAuthentication
from plane.app.serializers import WorkSpaceSerializer
from plane.bgtasks.event_tracking_task import track_event
from plane.bgtasks.workspace_seed_task import workspace_seed
from plane.db.models import Workspace, WorkspaceMember
from plane.license.api.permissions import InstanceAdminPermission
from plane.license.utils.instance_value import get_configuration_value
from plane.utils.analytics_events import WORKSPACE_CREATED
from plane.utils.url import contains_url

# Role 20 is WorkspaceMember's role value for Admin/Owner (mirrors the web
# onboarding flow: whoever creates a workspace owns it).
WORKSPACE_OWNER_ROLE = 20

# The only body keys POST /api/v1/workspaces/ accepts — the three the contract
# above promises. Everything else is a 400, and the serializer is fed from this
# set rather than from raw request.data.
#
# WHY: WorkSpaceSerializer is core and declares `fields = "__all__"` with a
# read_only_fields list that covers id/created_by/updated_by/created_at/
# updated_at/owner/logo_url but NOT `deleted_at`, `logo`, `logo_asset`,
# `timezone` or `background_color`. Handing it request.data therefore made
# those five writable. `deleted_at` is the one that bites: SoftDeletionManager
# filters `deleted_at__isnull=True`, so a POSTed `deleted_at` committed a 201
# row that is invisible to every default-manager query — including this view's
# own 409 pre-check and the serializer's UniqueValidator — while the database's
# unique index on `slug` still holds. Every later create of that slug would then
# 409 against a workspace no API can see, with no path to free it (the
# soft-delete path that appends `__<epoch>` to the slug never runs).
# `logo_asset` was a second hole: an unscoped FK to any FileAsset on the
# instance, so a new workspace could serve another workspace's asset.
CREATE_WORKSPACE_ALLOWED_FIELDS = frozenset({"name", "slug", "organization_size"})

# Written as concatenated literals rather than one triple-quoted block purely
# so every SOURCE line fits ruff's 120-char limit — the rendered string is
# byte-identical to the block as written, and the same text is duplicated
# verbatim in docs/FORK.md. Do not reflow it; both copies are the contract.
CREATE_WORKSPACE_CONTRACT = (
    "POST /api/v1/workspaces/\n"
    "Auth: X-API-Key (BaseAPIView). Permission: InstanceAdminPermission -> 403 "
    '{"error": "...", "error_code": "INSTANCE_ADMIN_REQUIRED"} otherwise.\n'
    '403 {"error": "...", "error_code": "WORKSPACE_CREATION_DISABLED"} when instance '
    "config DISABLE_WORKSPACE_CREATION is on (same gate as the web app).\n"
    'Body: {"name": str (required, <=80, no URL), "slug": str (required, <=48, '
    '^[a-zA-Z0-9_-]+$, not a restricted slug), "organization_size": str|null '
    "(optional, <=20, pass-through)}\n"
    "201: WorkSpaceSerializer output (id, name, slug, owner, organization_size, "
    'logo_url, created_at, updated_at, ...) plus {"role": 20, "total_members": 1}\n'
    '400: {"error": "...", "error_code": "UNEXPECTED_FIELDS"} when the body carries a key other '
    "than the three above; otherwise serializer/field errors (DRF shape) or "
    '{"error": "...", "error_code": "..."} for the manual caps\n'
    '409: {"slug": "The workspace with the slug already exists", "error_code": "WORKSPACE_SLUG_EXISTS"}\n'
    "Side effects: caller becomes Owner (WorkspaceMember role=20); workspace_seed "
    "Celery task queued; WORKSPACE_CREATED event tracked."
)


class InstanceAdminRequiredPermission(InstanceAdminPermission):
    """InstanceAdminPermission, but with a machine-readable 403 body.

    The base class returns False, which DRF renders as
    {"detail": "You do not have permission to perform this action."} — a body an
    API consumer cannot branch on. This endpoint promises
    {"error": ..., "error_code": "INSTANCE_ADMIN_REQUIRED"}, so the refusal is
    raised instead of returned.

    Anonymous callers still return False rather than raising: DRF's
    `permission_denied` runs the authenticator's own 401/403 negotiation for
    them, and raising here would pre-empt that.
    """

    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False
        if not super().has_permission(request, view):
            raise PermissionDenied(
                {
                    "error": "Instance admin permission is required to create a workspace",
                    "error_code": "INSTANCE_ADMIN_REQUIRED",
                }
            )
        return True


class WorkspaceCreateAPIEndpoint(BaseAPIView):
    """POST /api/v1/workspaces/ — create a workspace, caller becomes its Owner.

    Instance-admin only (option (a) in the issue): a self-hosted single-tenant
    instance has no tenant boundary to scope "any authenticated user may mint a
    workspace" to, so the API matches what the UI effectively enforces — the
    god-mode Workspaces screen is instance-admin gated too. An API key that is
    merely a workspace member is refused.

    Behaviour mirrors the web app's WorkSpaceViewSet.create
    (plane/app/views/workspace/base.py) so API- and UI-created workspaces are
    indistinguishable: same serializer (slug regex, RESTRICTED_WORKSPACE_SLUGS,
    no-URL-in-name), same name/slug caps, same DISABLE_WORKSPACE_CREATION gate,
    same owner membership row, same seed + analytics side effects.
    """

    serializer_class = WorkSpaceSerializer
    model = Workspace
    permission_classes = [InstanceAdminRequiredPermission]

    @extend_schema(
        tags=["Workspaces"],
        description=CREATE_WORKSPACE_CONTRACT,
        request=WorkSpaceSerializer,
        responses={201: WorkSpaceSerializer},
    )
    def post(self, request):
        try:
            (DISABLE_WORKSPACE_CREATION,) = get_configuration_value(
                [
                    {
                        "key": "DISABLE_WORKSPACE_CREATION",
                        "default": os.environ.get("DISABLE_WORKSPACE_CREATION", "0"),
                    }
                ]
            )

            if DISABLE_WORKSPACE_CREATION == "1":
                return Response(
                    {
                        "error": "Workspace creation is not allowed",
                        "error_code": "WORKSPACE_CREATION_DISABLED",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            # A non-object body (a bare JSON list, say) is not a mapping and has
            # no keys to whitelist; treat it as empty so the missing-name/slug
            # check below answers it, rather than letting set()/the serializer
            # raise a 500. QueryDict and dict both land on the dict branch.
            body = request.data if isinstance(request.data, dict) else {}

            # Refuse, rather than silently drop, a body key outside the
            # contract: this is a machine-facing API, and a client that sends
            # `deleted_at` or `logo_asset` needs to be told its field is not
            # honoured. The serializer below is fed from the same whitelist, so
            # the security control does not depend on this check being reached.
            unexpected = sorted(set(body) - CREATE_WORKSPACE_ALLOWED_FIELDS)
            if unexpected:
                return Response(
                    {
                        "error": f"Unexpected field(s): {', '.join(unexpected)}. "
                        "Allowed: name, slug, organization_size",
                        "error_code": "UNEXPECTED_FIELDS",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = WorkSpaceSerializer(
                data={key: value for key, value in body.items() if key in CREATE_WORKSPACE_ALLOWED_FIELDS}
            )

            slug = body.get("slug", False)
            name = body.get("name", False)

            if not name or not slug:
                return Response(
                    {
                        "error": "Both name and slug are required",
                        "error_code": "WORKSPACE_NAME_AND_SLUG_REQUIRED",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Type check before len(): the caps below are a documented 400, but
            # `len(123)` is a TypeError that escapes the view entirely and
            # surfaces as a 500. The serializer would reject a non-string on the
            # next line anyway — this just fails it as a 400 first.
            if not isinstance(name, str) or not isinstance(slug, str):
                return Response(
                    {
                        "error": "Both name and slug must be strings",
                        "error_code": "WORKSPACE_NAME_AND_SLUG_INVALID",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if len(name) > 80 or len(slug) > 48:
                return Response(
                    {
                        "error": "The maximum length for name is 80 and for slug is 48",
                        "error_code": "WORKSPACE_NAME_OR_SLUG_TOO_LONG",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if contains_url(name):
                return Response(
                    {
                        "error": "Name cannot contain a URL",
                        "error_code": "WORKSPACE_NAME_CONTAINS_URL",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # A slug collision is a 409 here, so it is detected explicitly.
            # DRF's UniqueValidator would reject it too, but as a 400
            # {"slug": ["Workspace with this slug already exists."]} raised out
            # of is_valid(raise_exception=True) — BEFORE save(), so the
            # IntegrityError branch below never sees the common case. Core's own
            # create() has the same short-circuit (its 409 is race-only); this
            # endpoint documents a 409 for a duplicate, so it must be one for
            # the deterministic case too. The IntegrityError branch stays as the
            # backstop for the race this check cannot close.
            if Workspace.objects.filter(slug=slug).exists():
                return Response(
                    {
                        "slug": "The workspace with the slug already exists",
                        "error_code": "WORKSPACE_SLUG_EXISTS",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            if serializer.is_valid(raise_exception=True):
                user_id = request.user.id

                # One transaction for both writes. A workspace with no
                # membership row is owner-less and invisible in every
                # membership-filtered list — including this app's own
                # UserWorkspacesAPIEndpoint — so a create must not be able to
                # commit half of itself.
                with transaction.atomic():
                    serializer.save(owner=request.user)
                    # Create Workspace member
                    WorkspaceMember.objects.create(
                        workspace_id=serializer.data["id"],
                        member=request.user,
                        role=WORKSPACE_OWNER_ROLE,
                    )

                    # Get total members and role. Counted inside the transaction
                    # so the row just written is visible.
                    data = serializer.data
                    data["total_members"] = WorkspaceMember.objects.filter(workspace_id=data["id"]).count()
                    data["role"] = WORKSPACE_OWNER_ROLE

                    # Dispatched AFTER the commit, not inside it: a broker
                    # outage used to escape as a 500 (or be misreported as a
                    # conflict) while the workspace and membership rows were
                    # already committed, which turned a retrying client into a
                    # permanent WORKSPACE_SLUG_EXISTS. `robust=True` keeps one
                    # failing dispatch from swallowing the other, and logs it
                    # instead of failing a create that has already happened.
                    workspace_id = data["id"]
                    transaction.on_commit(lambda: workspace_seed.delay(workspace_id), robust=True)

                    transaction.on_commit(
                        lambda: track_event.delay(
                            user_id=user_id,
                            event_name=WORKSPACE_CREATED,
                            slug=data["slug"],
                            event_properties={
                                "user_id": user_id,
                                "workspace_id": data["id"],
                                "workspace_slug": data["slug"],
                                "role": "owner",
                                "workspace_name": data["name"],
                                "created_at": data["created_at"],
                            },
                        ),
                        robust=True,
                    )

                return Response(data, status=status.HTTP_201_CREATED)

        except IntegrityError as e:
            if "already exists" in str(e):
                return Response(
                    {
                        "slug": "The workspace with the slug already exists",
                        "error_code": "WORKSPACE_SLUG_EXISTS",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            # Any other integrity violation is not a conflict the caller can act
            # on, and the transaction above has already rolled back, so there is
            # no half-created workspace left to describe. There is deliberately
            # no generic WORKSPACE_CREATE_CONFLICT body here: it would have been
            # the only 409 with no way for a client to distinguish it from a
            # slug collision. Re-raise instead and let it surface as the
            # integrity error it is.
            raise


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
