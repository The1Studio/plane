# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) create-workspace endpoint — proves the write-side
# bootstrap the discovery endpoint (test_workspace_ext_db.py) cannot provide:
# the slug a v1 client needs can now be MINTED with the same API key that will
# use it, instead of being copied out of a browser address bar.
#
# TransactionTestCase (mirrors github_ext/tests/test_api_config.py), real
# Postgres, no mocking of the unit under test. Authentication is REAL —
# APIClient.credentials(HTTP_X_API_KEY=<token>) — never force_authenticate, so a
# regression that drops APIKeyAuthentication from api_views.py fails these tests
# with 401 instead of a false green.
#
# workspace_seed is a Celery task and plane/settings/test.py sets no eager mode,
# so .delay would try to reach a broker. Both dispatches are patched, and the
# assertions check they were called with the NEW workspace's id — an endpoint
# that returns 201 but forgets to seed would otherwise pass unnoticed.

from unittest.mock import patch

import uuid

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import APIToken, Workspace, WorkspaceMember

URL = "/api/v1/workspaces/"
ROLE_OWNER = 20
ROLE_MEMBER = 15


# ---------------------------------------------------------------------------
# ORM helpers
# ---------------------------------------------------------------------------


def _user():
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"user_{uid}", email=f"u-{uid}@test.invalid", password="x")


def _instance_admin(user, role=ROLE_OWNER):
    """Register `user` as an instance admin so InstanceAdminPermission passes.
    Creates the singleton Instance row on first call."""
    from plane.license.models import Instance, InstanceAdmin

    instance = Instance.objects.first()
    if instance is None:
        instance = Instance.objects.create(
            instance_name="test-instance",
            instance_id="test-instance-id",
            current_version="1.0.0",
            last_checked_at=timezone.now(),
        )
    return InstanceAdmin.objects.create(user=user, instance=instance, role=role)


def _workspace_member(ws, user, role=ROLE_OWNER):
    return WorkspaceMember.objects.create(workspace=ws, member=user, role=role, is_active=True)


def _api_client(user):
    """Create a real APIToken for `user` and authenticate with it via the
    X-Api-Key header — the same way MCP/SDK consumers authenticate."""
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=APIToken.objects.create(user=user).token)
    return client


def _payload(**overrides):
    body = {"name": "DevOps", "slug": f"devops-{uuid.uuid4().hex[:8]}"}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# 201 — happy path
# ---------------------------------------------------------------------------


class CreateWorkspaceHappyPathTests(TransactionTestCase):
    def test_instance_admin_creates_workspace(self):
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)
        body = _payload(organization_size="1-10")

        with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed, patch(
            "plane.workspace_ext.api_views.track_event.delay"
        ) as track:
            resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 201)

        # The row exists and carries the caller as owner.
        ws = Workspace.objects.get(slug=body["slug"])
        self.assertEqual(ws.name, body["name"])
        self.assertEqual(ws.owner_id, admin.id)
        self.assertEqual(ws.organization_size, "1-10")

        # Caller owns it: exactly one member row, role 20.
        members = WorkspaceMember.objects.filter(workspace=ws)
        self.assertEqual(members.count(), 1)
        membership = members.get()
        self.assertEqual(membership.member_id, admin.id)
        self.assertEqual(membership.role, ROLE_OWNER)
        self.assertTrue(membership.is_active)

        # Response shape: serializer fields + the two computed ones.
        # resp.data["id"] is the UUID object pre-rendering (DRF resolves the PK
        # as-is) and it serialises to the same hyphenated string the workspace
        # was looked up by, so compare through str().
        self.assertEqual(str(resp.data["id"]), str(ws.id))
        self.assertEqual(resp.data["slug"], body["slug"])
        self.assertEqual(resp.data["name"], body["name"])
        self.assertEqual(resp.data["role"], ROLE_OWNER)
        self.assertEqual(resp.data["total_members"], 1)
        self.assertIn("created_at", resp.data)
        self.assertIn("logo_url", resp.data)

        # Both side-effect dispatches fired, with the NEW workspace's id.
        seed.assert_called_once()
        self.assertEqual(str(seed.call_args.args[0]), str(ws.id))
        track.assert_called_once()
        self.assertEqual(track.call_args.kwargs["event_name"], "workspace_created")
        self.assertEqual(
            str(track.call_args.kwargs["event_properties"]["workspace_id"]), str(ws.id)
        )
        self.assertEqual(track.call_args.kwargs["event_properties"]["workspace_slug"], body["slug"])

    def test_organization_size_is_optional_and_passed_through(self):
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)
        body = _payload()

        with patch("plane.workspace_ext.api_views.workspace_seed.delay"), patch(
            "plane.workspace_ext.api_views.track_event.delay"
        ):
            resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(Workspace.objects.get(slug=body["slug"]).organization_size)

    def test_route_is_registered_under_api_v1(self):
        from django.urls import resolve

        from plane.workspace_ext.api_views import WorkspaceCreateAPIEndpoint

        match = resolve("/api/v1/workspaces/")
        self.assertIs(match.func.view_class, WorkspaceCreateAPIEndpoint)

    def test_does_not_shadow_a_core_workspaces_collection_route(self):
        """`workspaces/` is registered here, and this app's urls are included
        BEFORE plane.api.urls — so if upstream ever adds a bare `workspaces/`
        collection route to the public API, this one silently wins and core's
        disappears for every consumer, with no error anywhere.

        Today there is none (every core v1 workspace route is
        `workspaces/<slug>/...`); the assertion is a tripwire on that fact, not
        a tautology. When it goes red, the fix is to reconcile the two routes —
        not to delete this test.
        """
        from plane.api.urls import urlpatterns as core_urls

        bare = [
            str(p.pattern)
            for p in core_urls
            if str(p.pattern).rstrip("^$") == "workspaces/"
        ]
        self.assertEqual(
            bare,
            [],
            "core now has a bare workspaces/ route — the fork's url must stop shadowing it",
        )


# ---------------------------------------------------------------------------
# 403 — authorization
# ---------------------------------------------------------------------------


class CreateWorkspacePermissionTests(TransactionTestCase):
    def test_no_api_key_returns_401(self):
        """No X-Api-Key header at all -> unauthenticated, never reaches the
        InstanceAdminPermission check."""
        resp = APIClient().post(URL, _payload(), format="json")
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(Workspace.objects.exists())

    def test_non_instance_admin_api_key_returns_403(self):
        """A valid API key whose user is a workspace ADMIN — but not an instance
        admin — cannot mint a workspace. This is the whole authorization
        decision: an API key is not a tenant, so minting is instance-admin only."""
        ws = Workspace.objects.create(name="Existing", slug="existing-ws", logo="", owner=_user())
        ws_admin = _user()
        _workspace_member(ws, ws_admin, role=ROLE_OWNER)
        client = _api_client(ws_admin)
        body = _payload()

        with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed, patch(
            "plane.workspace_ext.api_views.track_event.delay"
        ):
            resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["error_code"], "INSTANCE_ADMIN_REQUIRED")
        self.assertFalse(Workspace.objects.filter(slug=body["slug"]).exists())
        seed.assert_not_called()

    def test_is_active_false_api_key_never_authenticates(self):
        """A deactivated APIToken raises AuthenticationFailed in
        APIKeyAuthentication.validate_api_token, so it never reaches the
        permission check — no instance-admin bypass via a stale key.

        Pinned as 403, not 401: DRF's AuthenticationFailed defaults to 403
        (exceptions.py) and its status is only rewritten to 401 when the
        authenticator has no authenticate_header(). APIKeyAuthentication sets
        media_type/www_authenticate_realm, so the header IS produced and 403
        stands. This is identical for every /api/v1/ endpoint on the instance —
        pinned here so a future change to the auth class is visible.

        Distinguish from test_no_api_key_returns_401: NO header leaves the
        request anonymous, which is NotAuthenticated (401).
        """
        user = _user()
        _instance_admin(user)
        token = APIToken.objects.create(user=user)
        token.is_active = False
        token.save(update_fields=["is_active"])

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=token.token)
        body = _payload()
        resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Workspace.objects.filter(slug=body["slug"]).exists())


# ---------------------------------------------------------------------------
# 403 — DISABLE_WORKSPACE_CREATION gate
# ---------------------------------------------------------------------------


class CreateWorkspaceDisabledTests(TransactionTestCase):
    def _client(self):
        admin = _user()
        _instance_admin(admin)
        return _api_client(admin)

    @patch.dict("os.environ", {"DISABLE_WORKSPACE_CREATION": "1"})
    def test_disabled_via_env_returns_403(self):
        client = self._client()
        body = _payload()

        with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed:
            resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_CREATION_DISABLED")
        self.assertFalse(Workspace.objects.filter(slug=body["slug"]).exists())
        seed.assert_not_called()

    def test_disabled_via_instance_configuration_returns_403(self):
        """SKIP_ENV_VAR=1 (the default) is what makes the InstanceConfiguration
        row authoritative — mirror the config-service path, not the env path."""
        from plane.license.models import InstanceConfiguration

        InstanceConfiguration.objects.create(
            key="DISABLE_WORKSPACE_CREATION", value="1", category="workspace"
        )
        client = self._client()
        body = _payload()

        with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed:
            resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_CREATION_DISABLED")
        self.assertFalse(Workspace.objects.filter(slug=body["slug"]).exists())
        seed.assert_not_called()


# ---------------------------------------------------------------------------
# 400 — validation
# ---------------------------------------------------------------------------


class CreateWorkspaceValidationTests(TransactionTestCase):
    def setUp(self):
        admin = _user()
        _instance_admin(admin)
        self.client = _api_client(admin)

    def _post(self, body):
        with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed, patch(
            "plane.workspace_ext.api_views.track_event.delay"
        ):
            resp = self.client.post(URL, body, format="json")
        return resp, seed

    def test_restricted_slug_returns_400(self):
        from plane.utils.constants import RESTRICTED_WORKSPACE_SLUGS

        resp, seed = self._post(_payload(slug=RESTRICTED_WORKSPACE_SLUGS[0]))

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Workspace.objects.filter(slug=RESTRICTED_WORKSPACE_SLUGS[0]).exists())
        seed.assert_not_called()

    def test_bad_slug_charset_returns_400(self):
        resp, seed = self._post(_payload(slug="not a slug!"))

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Workspace.objects.filter(slug="not a slug!").exists())
        seed.assert_not_called()

    def test_url_in_name_returns_400(self):
        resp, seed = self._post(_payload(name="https://evil.example.com"))

        self.assertEqual(resp.status_code, 400)
        seed.assert_not_called()

    def test_name_over_80_chars_returns_400(self):
        resp, seed = self._post(_payload(name="x" * 81))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_NAME_OR_SLUG_TOO_LONG")
        seed.assert_not_called()

    def test_slug_over_48_chars_returns_400(self):
        resp, seed = self._post(_payload(slug="s" * 49))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_NAME_OR_SLUG_TOO_LONG")
        seed.assert_not_called()

    def test_missing_name_returns_400(self):
        resp, seed = self._post({"slug": "no-name-here"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_NAME_AND_SLUG_REQUIRED")
        seed.assert_not_called()

    def test_missing_slug_returns_400(self):
        resp, seed = self._post({"name": "No Slug Here"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_NAME_AND_SLUG_REQUIRED")
        seed.assert_not_called()

    def test_non_string_name_returns_400_not_500(self):
        """`len(123)` is a TypeError, not a validation error — a non-string must
        be refused as a 400 rather than escaping the view as a 500."""
        resp, seed = self._post({"name": 123, "slug": "numeric-name"})

        self.assertEqual(resp.status_code, 400)
        seed.assert_not_called()


# ---------------------------------------------------------------------------
# 409 — duplicate slug
# ---------------------------------------------------------------------------


class CreateWorkspaceConflictTests(TransactionTestCase):
    def test_duplicate_slug_returns_409(self):
        existing = Workspace.objects.create(name="Taken", slug="taken-slug", logo="", owner=_user())
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)

        with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed, patch(
            "plane.workspace_ext.api_views.track_event.delay"
        ):
            resp = client.post(URL, {"name": "Also Taken", "slug": "taken-slug"}, format="json")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_SLUG_EXISTS")
        # The original is untouched and no second row was written.
        self.assertEqual(Workspace.objects.filter(slug="taken-slug").count(), 1)
        self.assertEqual(Workspace.objects.get(slug="taken-slug").id, existing.id)
        seed.assert_not_called()
