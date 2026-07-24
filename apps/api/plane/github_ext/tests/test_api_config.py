# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) mirror of test_config.py — proves the three-tier
# status-automation config CRUD is reachable via API-key auth (the whole
# point of api_views.py/api_urls.py: the session-only internal routes
# 401 every external client — MCP server, node/python SDKs — that
# authenticates with X-Api-Key).
#
# TransactionTestCase (mirrors test_config.py style), real Postgres, no
# mocking of the unit under test. Unlike test_config.py (which uses
# APIClient.force_authenticate to bypass authentication_classes), these tests
# authenticate for real via APIClient.credentials(HTTP_X_API_KEY=<token>) —
# so a regression that drops APIKeyAuthentication from api_views.py fails
# these tests with 401, not a false green.

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import APIToken
from plane.github_ext.models import StateTransitionConfig
from plane.github_ext.services.state_transition import DEFAULT_RULES
from plane.github_ext.tests.test_webhook import _project, _user, _workspace

ROLE_ADMIN = 20
ROLE_MEMBER = 15


# ---------------------------------------------------------------------------
# ORM helpers (mirror test_config.py / test_webhook.py)
# ---------------------------------------------------------------------------

def _wmember(ws, user, role=ROLE_ADMIN):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(
        workspace=ws, member=user, role=role, is_active=True
    )


def _state(ws, proj, name, group="started"):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws, project=proj, name=name, color="#fff", group=group
    )


def _instance_admin(user, role=ROLE_ADMIN):
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


def _api_token(user):
    """Create a real APIToken for `user` and return the raw token string —
    used via APIClient.credentials(HTTP_X_API_KEY=<token>) so requests are
    authenticated the same way MCP/SDK consumers authenticate."""
    return APIToken.objects.create(user=user).token


def _api_client(user):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=_api_token(user))
    return client


# ---------------------------------------------------------------------------
# Tier 1 — instance-global config  (/api/v1/github-config/, instance admin)
# ---------------------------------------------------------------------------

class GithubGlobalConfigAPITests(TransactionTestCase):
    URL = "/api/v1/github-config/"

    def test_get_api_key_authenticated_returns_defaults(self):
        """The whole point: an API-key-authenticated request succeeds where
        the session-only internal route would 401 every external client."""
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)

        resp = client.get(self.URL)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"], DEFAULT_RULES)

    def test_put_api_key_authenticated_validates_and_saves(self):
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)

        resp = client.put(
            self.URL, {"rules": {"pr_opened": "In Progress"}}, format="json"
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"], {"pr_opened": "In Progress"})
        row = StateTransitionConfig.objects.get(scope="global")
        self.assertEqual(row.rules, {"pr_opened": "In Progress"})

    def test_no_api_key_returns_401(self):
        """No X-Api-Key header at all -> unauthenticated, never reaches the
        InstanceAdminPermission check."""
        resp = APIClient().get(self.URL)
        self.assertEqual(resp.status_code, 401)

    def test_put_non_instance_admin_403(self):
        ws = _workspace()
        ws_admin = _user()
        _wmember(ws, ws_admin, role=ROLE_ADMIN)
        client = _api_client(ws_admin)

        resp = client.put(
            self.URL, {"rules": {"pr_opened": "In Progress"}}, format="json"
        )

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(StateTransitionConfig.objects.filter(scope="global").exists())

    def test_put_invalid_event_key_returns_400(self):
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)

        resp = client.put(
            self.URL, {"rules": {"not_a_real_event": "In Progress"}}, format="json"
        )

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(StateTransitionConfig.objects.filter(scope="global").exists())

    def test_put_empty_string_value_returns_400(self):
        admin = _user()
        _instance_admin(admin)
        client = _api_client(admin)

        resp = client.put(self.URL, {"rules": {"pr_opened": "   "}}, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(StateTransitionConfig.objects.filter(scope="global").exists())


# ---------------------------------------------------------------------------
# Tier 2 — per-workspace config  (/api/v1/workspaces/<slug>/github-config/)
# ---------------------------------------------------------------------------

class GithubWorkspaceConfigAPITests(TransactionTestCase):
    def _url(self, slug):
        return f"/api/v1/workspaces/{slug}/github-config/"

    def test_get_api_key_authenticated_resolves_workspace_over_global(self):
        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)

        StateTransitionConfig.objects.create(
            scope="global", rules={"pr_opened": "In Review"}
        )
        StateTransitionConfig.objects.create(
            scope="workspace", workspace=ws, rules={"pr_opened": "In Progress"}
        )

        client = _api_client(member)
        resp = client.get(self._url(ws.slug))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"]["pr_opened"], "In Progress")
        self.assertEqual(resp.data["rules"]["pr_merged"], DEFAULT_RULES["pr_merged"])

    def test_get_unknown_workspace_returns_404(self):
        member = _user()
        client = _api_client(member)
        resp = client.get(self._url("no-such-workspace"))
        self.assertEqual(resp.status_code, 404)

    def test_get_non_member_403(self):
        """Workspace member requirement is real — a valid API key belonging
        to a user with NO membership row is a 403, not a 200."""
        ws = _workspace()
        outsider = _user()
        client = _api_client(outsider)

        resp = client.get(self._url(ws.slug))
        self.assertEqual(resp.status_code, 403)

    def test_put_member_403_admin_200(self):
        ws = _workspace()
        member = _user()
        admin = _user()
        _wmember(ws, member, role=ROLE_MEMBER)
        _wmember(ws, admin, role=ROLE_ADMIN)
        payload = {"rules": {"pr_opened": "In Progress"}}

        member_client = _api_client(member)
        self.assertEqual(
            member_client.put(self._url(ws.slug), payload, format="json").status_code,
            403,
        )

        admin_client = _api_client(admin)
        self.assertEqual(
            admin_client.put(self._url(ws.slug), payload, format="json").status_code,
            200,
        )

    def test_put_shape_only_no_state_check(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        client = _api_client(admin)

        resp = client.put(
            self._url(ws.slug),
            {"rules": {"pr_opened": "Some Workspace Default"}},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        row = StateTransitionConfig.objects.get(scope="workspace", workspace=ws)
        self.assertEqual(row.rules, {"pr_opened": "Some Workspace Default"})

    def test_put_bad_event_key_returns_400(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        client = _api_client(admin)

        resp = client.put(
            self._url(ws.slug),
            {"rules": {"pr_closed_without_merge": "Done"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            StateTransitionConfig.objects.filter(scope="workspace", workspace=ws).exists()
        )

    def test_put_empty_string_value_returns_400(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        client = _api_client(admin)

        resp = client.put(
            self._url(ws.slug), {"rules": {"pr_opened": ""}}, format="json"
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Tier 3 — per-project config
# (/api/v1/workspaces/<slug>/projects/<id>/github-config/)
# ---------------------------------------------------------------------------

class GithubProjectConfigAPITests(TransactionTestCase):
    def _url(self, slug, project_id):
        return f"/api/v1/workspaces/{slug}/projects/{project_id}/github-config/"

    def test_get_project_beats_workspace_beats_global(self):
        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)
        proj = _project(ws, name="Proj", identifier="PRJ")
        _state(ws, proj, name="In Progress", group="started")

        StateTransitionConfig.objects.create(
            scope="global",
            rules={"pr_opened": "GlobalState", "pr_ready_for_review": "GlobalReview"},
        )
        StateTransitionConfig.objects.create(
            scope="workspace",
            workspace=ws,
            rules={"pr_ready_for_review": "WorkspaceReview"},
        )
        StateTransitionConfig.objects.create(
            scope="project", project=proj, rules={"pr_opened": "In Progress"}
        )

        client = _api_client(member)
        resp = client.get(self._url(ws.slug, proj.id))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"]["pr_opened"], "In Progress")
        self.assertEqual(resp.data["rules"]["pr_ready_for_review"], "WorkspaceReview")
        self.assertEqual(resp.data["rules"]["pr_merged"], DEFAULT_RULES["pr_merged"])

    def test_get_unknown_project_returns_404(self):
        import uuid

        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)

        client = _api_client(member)
        resp = client.get(self._url(ws.slug, uuid.uuid4()))
        self.assertEqual(resp.status_code, 404)

    def test_slug_not_owning_project_returns_404(self):
        """Cross-workspace guard, exercised through the public API too: a
        real project_id under a DIFFERENT workspace's slug is a 404 — the
        ws-role gate can't be satisfied against an unrelated workspace."""
        ws_a = _workspace()
        ws_b = _workspace()
        attacker = _user()
        _wmember(ws_b, attacker, role=ROLE_ADMIN)
        proj_a = _project(ws_a, name="Secret", identifier="SEC")

        client = _api_client(attacker)
        resp = client.get(self._url(ws_b.slug, proj_a.id))
        self.assertEqual(resp.status_code, 404)

    def test_put_valid_state_name_saves_and_returns_200(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        proj = _project(ws, name="Proj2", identifier="PR2")
        _state(ws, proj, name="In Review", group="started")

        client = _api_client(admin)
        resp = client.put(
            self._url(ws.slug, proj.id),
            {"rules": {"pr_ready_for_review": "In Review"}},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"], {"pr_ready_for_review": "In Review"})
        row = StateTransitionConfig.objects.get(scope="project", project=proj)
        self.assertEqual(row.rules, {"pr_ready_for_review": "In Review"})

    def test_put_nonexistent_state_name_returns_400(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        proj = _project(ws, name="Proj3", identifier="PR3")

        client = _api_client(admin)
        resp = client.put(
            self._url(ws.slug, proj.id),
            {"rules": {"pr_opened": "Nonexistent State"}},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("not found in project", resp.data["error"])
        self.assertFalse(
            StateTransitionConfig.objects.filter(scope="project", project=proj).exists()
        )

    def test_put_bad_event_key_returns_400(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        proj = _project(ws, name="Proj4", identifier="PR4")
        _state(ws, proj, name="Done", group="completed")

        client = _api_client(admin)
        resp = client.put(
            self._url(ws.slug, proj.id),
            {"rules": {"pr_closed_without_merge": "Done"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_empty_string_value_returns_400(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        proj = _project(ws, name="Proj4b", identifier="PR4B")

        client = _api_client(admin)
        resp = client.put(
            self._url(ws.slug, proj.id),
            {"rules": {"pr_opened": ""}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_non_admin_403_admin_200(self):
        ws = _workspace()
        non_admin = _user()
        admin = _user()
        _wmember(ws, non_admin, role=ROLE_MEMBER)
        _wmember(ws, admin, role=ROLE_ADMIN)
        proj = _project(ws, name="Proj5", identifier="PR5")
        _state(ws, proj, name="In Progress", group="started")
        payload = {"rules": {"pr_opened": "In Progress"}}

        non_admin_client = _api_client(non_admin)
        self.assertEqual(
            non_admin_client.put(
                self._url(ws.slug, proj.id), payload, format="json"
            ).status_code,
            403,
        )

        admin_client = _api_client(admin)
        self.assertEqual(
            admin_client.put(
                self._url(ws.slug, proj.id), payload, format="json"
            ).status_code,
            200,
        )
