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

import re
import textwrap
import uuid
from pathlib import Path
from unittest.mock import patch

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
        # all_objects (unfiltered) throughout this file's negative assertions:
        # the default manager hides soft-deleted rows, which is exactly the
        # state a mass-assignment regression leaves behind.
        self.assertFalse(Workspace.all_objects.exists())

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
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
        seed.assert_not_called()

    def test_is_active_false_api_key_never_authenticates(self):
        """A deactivated APIToken raises AuthenticationFailed in
        APIKeyAuthentication.validate_api_token, so it is REFUSED BY THE
        AUTHENTICATOR and never reaches the permission check — no
        instance-admin bypass via a stale key.

        The status alone cannot tell that apart from the opposite failure. An
        INSTANCE_ADMIN_REQUIRED refusal is also a 403, so a regression where
        the deactivated key authenticated successfully and was then stopped by
        the permission gate would keep a bare `assertEqual(403)` green while the
        bypass was live. The two are distinguished by BODY:

        - authentication refusal is DRF's own AuthenticationFailed, rendered as
          DRF's default `{"detail": ...}` (detail = "Given API token is not
          valid") with no `error_code` key at all;
        - the permission gate raises our `PermissionDenied` carrying
          `error_code: "INSTANCE_ADMIN_REQUIRED"`.

        Status is 403 rather than 401 for the reason DRF actually gives:
        AuthenticationFailed is rewritten to 401 only when the authenticator
        supplies an `authenticate_header()`. APIKeyAuthentication defines
        `www_authenticate_realm` and `media_type` as class constants but never
        overrides `authenticate_header`, so it inherits the base class's `None`
        return and `rest_framework/views.py:handle_exception` leaves the 403.

        The 401 on the anonymous path is NOT DRF's doing either: it comes from
        the fork's own handler (`plane/authentication/adapter/exception.py`),
        which rewrites NotAuthenticated to 401 and is wired as
        REST_FRAMEWORK["EXCEPTION_HANDLER"] in `plane/settings/common.py`.
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
        # Refused at authentication, not at authorization. An error_code here
        # would mean the key authenticated and the bypass was live.
        self.assertEqual(str(resp.data["detail"]), "Given API token is not valid")
        self.assertNotIn("error_code", resp.data)
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())

    def test_instance_admin_role_at_the_lower_boundary_can_create(self):
        """InstanceAdminPermission gates on `role__gte=15`, and every other test
        in this file creates its admin with the default role 20 — so the
        boundary itself was untested: loosening the gate to `role__gte=1` would
        pass the whole suite. 15 is the lowest role that must pass."""
        admin = _user()
        _instance_admin(admin, role=15)
        client = _api_client(admin)
        body = _payload()

        with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed, patch(
            "plane.workspace_ext.api_views.track_event.delay"
        ):
            resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Workspace.objects.get(slug=body["slug"]).owner_id, admin.id)
        seed.assert_called_once()

    def test_instance_admin_role_below_the_boundary_returns_403(self):
        """Every role under 15 is refused with the machine-readable body. 14
        pins the off-by-one; 10 and 5 are the real ROLE_CHOICES members below
        the gate (Admin is 15, Member 10, Guest 5)."""
        for role in (14, 10, 5):
            with self.subTest(role=role):
                user = _user()
                _instance_admin(user, role=role)
                client = _api_client(user)
                body = _payload()

                with patch("plane.workspace_ext.api_views.workspace_seed.delay") as seed, patch(
                    "plane.workspace_ext.api_views.track_event.delay"
                ):
                    resp = client.post(URL, body, format="json")

                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.data["error_code"], "INSTANCE_ADMIN_REQUIRED")
                self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
                seed.assert_not_called()


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
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
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
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
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
        self.assertFalse(Workspace.all_objects.filter(slug=RESTRICTED_WORKSPACE_SLUGS[0]).exists())
        seed.assert_not_called()

    def test_bad_slug_charset_returns_400(self):
        resp, seed = self._post(_payload(slug="not a slug!"))

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Workspace.all_objects.filter(slug="not a slug!").exists())
        seed.assert_not_called()

    def test_url_in_name_returns_400(self):
        """Pins the VIEW's own guard, not the serializer's.

        Both reject this input with a 400 — the serializer's `validate_name`
        calls the same `contains_url` — so a bare status assertion passes with
        the view's `contains_url` block deleted entirely. The `error_code` is
        what distinguishes them: `WORKSPACE_NAME_CONTAINS_URL` is raised by the
        view and only by the view, whereas the serializer would have produced a
        DRF field-error body with no `error_code` at all.
        """
        resp, seed = self._post(_payload(name="https://evil.example.com"))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "WORKSPACE_NAME_CONTAINS_URL")
        # Unfiltered manager: the default manager hides soft-deleted rows, which
        # is exactly the state a mass-assignment regression would create.
        self.assertFalse(Workspace.all_objects.filter(name="https://evil.example.com").exists())
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


class CreateWorkspaceBodyWhitelistTests(TransactionTestCase):
    """The body is a three-field contract, and the serializer is core.

    WorkSpaceSerializer declares `fields = "__all__"` with a read_only_fields
    list that covers owner/logo_url/id/created_by/updated_by/created_at/
    updated_at but NOT deleted_at, logo, logo_asset, timezone or
    background_color. Feeding it raw request.data therefore made all five
    writable over a public API key. `deleted_at` is the destructive one: the row
    commits, SoftDeletionManager hides it from every default-manager query, and
    the database's `unique=True` on slug keeps squatting the name — so the slug
    is unrecoverable through the API.

    Every negative assertion here reads through `Workspace.all_objects`, the
    UNFILTERED manager. Asserting on `Workspace.objects` would be exactly the
    check the bug defeats: a born-soft-deleted row is invisible to it.
    """

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

    def test_deleted_at_is_rejected_and_creates_nothing(self):
        """The blocker. A POSTed deleted_at must not mint a workspace that the
        default manager cannot see but the unique slug index can."""
        body = _payload(deleted_at="2020-01-01T00:00:00Z")
        resp, seed = self._post(body)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "UNEXPECTED_FIELDS")
        self.assertIn("deleted_at", resp.data["error"])
        # Unfiltered: the whole point is that the row must not exist at all,
        # regardless of which manager can see it.
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
        seed.assert_not_called()

    def test_owner_is_rejected_and_cannot_be_forged(self):
        """`owner` is already read_only on the serializer and forced to the
        caller by save(owner=request.user), so it is not a live hole — it is
        pinned here so the whitelist cannot regress into accepting it."""
        victim = _user()
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)
        body = _payload(owner=str(victim.id))

        with patch("plane.workspace_ext.api_views.workspace_seed.delay"), patch(
            "plane.workspace_ext.api_views.track_event.delay"
        ):
            resp = client.post(URL, body, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "UNEXPECTED_FIELDS")
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())

    def test_logo_is_rejected_and_creates_nothing(self):
        body = _payload(logo="https://evil.example.com/logo.png")
        resp, seed = self._post(body)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "UNEXPECTED_FIELDS")
        self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
        seed.assert_not_called()

    def test_status_only_fields_are_rejected(self):
        """The rest of the serializer's accidental writable set. All of these
        are refused in the same way, so they are one parametrised test rather
        than five near-identical ones."""
        for key, value in (
            ("logo_asset", str(uuid.uuid4())),
            ("timezone", "Asia/Ho_Chi_Minh"),
            ("background_color", "#123456"),
            ("role", 20),
            ("total_members", 99),
        ):
            with self.subTest(field=key):
                body = _payload(**{key: value})
                resp, seed = self._post(body)

                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.data["error_code"], "UNEXPECTED_FIELDS")
                self.assertIn(key, resp.data["error"])
                self.assertFalse(Workspace.all_objects.filter(slug=body["slug"]).exists())
                seed.assert_not_called()

    def test_the_three_contract_fields_are_still_accepted(self):
        """The whitelist must not be so tight that it breaks the contract it
        exists to enforce."""
        body = _payload(organization_size="11-50")
        resp, seed = self._post(body)

        self.assertEqual(resp.status_code, 201)
        ws = Workspace.objects.get(slug=body["slug"])
        self.assertEqual(ws.organization_size, "11-50")
        seed.assert_called_once()

    def test_unexpected_field_is_reported_together_with_its_siblings(self):
        """The 400 names every offending key, so a client is not left fixing
        one field per round trip."""
        body = _payload(deleted_at="2020-01-01T00:00:00Z", logo="x")
        resp, seed = self._post(body)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("deleted_at", resp.data["error"])
        self.assertIn("logo", resp.data["error"])
        seed.assert_not_called()


class CreateWorkspaceContractFenceTests(TransactionTestCase):
    """`CREATE_WORKSPACE_CONTRACT` and the fenced block in docs/FORK.md are two
    copies of one contract, and nothing enforced that. The constant's own
    comment calls them "the contract"; a test is what makes that true.

    This reads the REAL docs/FORK.md, extracts the fence and compares after
    dedent (the block sits indented under a list item, so its lines carry two
    leading spaces that textwrap.dedent strips).
    """

    def _fork_md(self):
        # apps/api/plane/workspace_ext/tests/ -> repo root is five levels up.
        # Anchored on __file__ rather than settings.BASE_DIR so it does not
        # depend on where the settings module happens to live.
        path = Path(__file__).resolve().parents[5] / "docs" / "FORK.md"
        self.assertTrue(path.is_file(), f"docs/FORK.md not found at {path}")
        return path.read_text(encoding="utf-8")

    def test_fork_md_fence_matches_the_contract_constant_byte_for_byte(self):
        from plane.workspace_ext.api_views import CREATE_WORKSPACE_CONTRACT

        match = re.search(r"\n  ```\n(.*?)\n  ```\n", self._fork_md(), re.S)
        self.assertIsNotNone(match, "the contract fence is missing from docs/FORK.md")

        fence = textwrap.dedent(match.group(1))
        self.assertEqual(
            fence,
            CREATE_WORKSPACE_CONTRACT,
            "docs/FORK.md's contract fence has drifted from CREATE_WORKSPACE_CONTRACT — "
            "they are two copies of one contract and must be edited together",
        )

    def test_contract_documents_every_error_code_the_view_can_return(self):
        """Every `error_code` the view can emit is either NAMED in the contract
        or covered by its generic manual-caps clause. A code in neither list is
        one a client cannot branch on.

        The codes are DERIVED from the view's own source rather than listed
        here, so adding a new response dict to api_views.py pushes on this test
        until the author classifies it — which is the drift gate that was
        missing. (The derived set also picks up the four codes the contract
        constant itself spells out; they are required to be named anyway, so
        that is consistent rather than circular.)

        Bidirectional by construction: `assertEqual` on the set means an
        already-classified code silently disappearing from the view is a
        failure too, so neither half can rot.
        """
        from plane.workspace_ext import api_views
        from plane.workspace_ext.api_views import CREATE_WORKSPACE_CONTRACT

        # Named one by one in the contract text.
        named_in_contract = {
            "INSTANCE_ADMIN_REQUIRED",
            "WORKSPACE_CREATION_DISABLED",
            "UNEXPECTED_FIELDS",
            "WORKSPACE_SLUG_EXISTS",
        }
        # Documented COLLECTIVELY, by the contract's
        # `{"error": "...", "error_code": "..."} for the manual caps` clause
        # rather than enumerated. Not exempt from review — just not required to
        # appear literally. Promote one to `named_in_contract` above if the
        # contract ever spells it out.
        covered_by_the_generic_clause = {
            "WORKSPACE_NAME_AND_SLUG_REQUIRED",
            "WORKSPACE_NAME_AND_SLUG_INVALID",
            "WORKSPACE_NAME_OR_SLUG_TOO_LONG",
            "WORKSPACE_NAME_CONTAINS_URL",
        }

        source = Path(api_views.__file__).read_text(encoding="utf-8")
        emitted = set(re.findall(r'"error_code":\s*"([A-Z_]+)"', source))
        self.assertTrue(emitted, "no error_code literals found — the extractor is broken")

        self.assertEqual(
            emitted,
            named_in_contract | covered_by_the_generic_clause,
            "the view emits error_code(s) this test has not classified — add the new code to "
            "CREATE_WORKSPACE_CONTRACT (and docs/FORK.md), or record it in "
            "covered_by_the_generic_clause if the contract's manual-caps clause genuinely covers it",
        )

        for code in sorted(named_in_contract):
            with self.subTest(error_code=code):
                self.assertIn(code, CREATE_WORKSPACE_CONTRACT)

        # The deleted generic conflict code must NOT be documented, because the
        # view no longer returns it.
        self.assertNotIn("WORKSPACE_CREATE_CONFLICT", CREATE_WORKSPACE_CONTRACT)
        self.assertNotIn("WORKSPACE_CREATE_CONFLICT", emitted)

    def test_contract_fence_is_the_first_fence_in_the_workspace_ext_section(self):
        """Guards the extractor itself. The regex above is unanchored, so it
        takes the FIRST fenced block in the file — if another fence is ever
        introduced ahead of the contract, the parity test would silently start
        comparing the wrong block and pass forever. This pins which block the
        extractor is actually reading."""
        from plane.workspace_ext.api_views import CREATE_WORKSPACE_CONTRACT

        fences = re.findall(r"\n  ```\n(.*?)\n  ```\n", self._fork_md(), re.S)
        self.assertGreaterEqual(len(fences), 1)
        self.assertEqual(
            textwrap.dedent(fences[0]),
            CREATE_WORKSPACE_CONTRACT,
            "the extractor no longer reads the contract fence — another fenced "
            "block was added ahead of it, so the parity check is comparing the "
            "wrong text",
        )


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
