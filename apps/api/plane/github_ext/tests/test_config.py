# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P2/P4 — status-automation config CRUD tests (views/config.py), three-tier
# scoping: instance-global -> per-workspace -> per-project.
#
# TransactionTestCase (mirrors test_webhook.py style), real Postgres, no
# mocking of the unit under test. Permission-layer auth is exercised via
# DRF's `APIClient.force_authenticate` (see
# workload/tests/test_workload_bulk.py TestBulkEstimatesHTTP): it bypasses
# `authentication_classes` (BaseSessionAuthentication) and sets
# `request.user` directly, so the ADMIN-vs-MEMBER distinction is enforced for
# real by `@allow_permission`'s own WorkspaceMember lookup, and the
# instance-admin gate by `InstanceAdminPermission`'s own InstanceAdmin lookup
# — not by the test double.

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from plane.github_ext.models import StateTransitionConfig
from plane.github_ext.services.state_transition import DEFAULT_RULES
from plane.github_ext.tests.test_webhook import _project, _user, _workspace

ROLE_ADMIN = 20
ROLE_MEMBER = 15


# ---------------------------------------------------------------------------
# ORM helpers (config-CRUD specific; mirror workload/tests/test_workload_bulk.py)
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


# ---------------------------------------------------------------------------
# Tier 1 — instance-global config  (/api/github/config/, instance admin)
# ---------------------------------------------------------------------------

class GithubGlobalConfigTests(TransactionTestCase):
    URL = "/api/github/config/"

    def setUp(self):
        self.client = APIClient()

    def test_get_returns_defaults_when_no_row(self):
        admin = _user()
        _instance_admin(admin)

        self.client.force_authenticate(user=admin)
        resp = self.client.get(self.URL)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"], DEFAULT_RULES)

    def test_get_non_instance_admin_403(self):
        """A workspace member who is NOT an instance admin cannot read the
        instance-wide default (the row is shared by every workspace)."""
        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_ADMIN)  # workspace admin, not instance

        self.client.force_authenticate(user=member)
        resp = self.client.get(self.URL)

        self.assertEqual(resp.status_code, 403)

    def test_put_non_instance_admin_403(self):
        ws = _workspace()
        ws_admin = _user()
        _wmember(ws, ws_admin, role=ROLE_ADMIN)

        self.client.force_authenticate(user=ws_admin)
        resp = self.client.put(
            self.URL, {"rules": {"pr_opened": "In Progress"}}, format="json"
        )

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(StateTransitionConfig.objects.filter(scope="global").exists())

    def test_put_instance_admin_validates_and_saves(self):
        admin = _user()
        _instance_admin(admin)
        self.client.force_authenticate(user=admin)

        resp_bad = self.client.put(
            self.URL, {"rules": {"not_a_real_event": "In Progress"}}, format="json"
        )
        self.assertEqual(resp_bad.status_code, 400)

        resp_ok = self.client.put(
            self.URL, {"rules": {"pr_opened": "In Progress"}}, format="json"
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertEqual(resp_ok.data["rules"], {"pr_opened": "In Progress"})
        row = StateTransitionConfig.objects.get(scope="global")
        self.assertEqual(row.rules, {"pr_opened": "In Progress"})


# ---------------------------------------------------------------------------
# Tier 2 — per-workspace config  (/api/github/<slug>/config/, ws admin)
# ---------------------------------------------------------------------------

class GithubWorkspaceConfigTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, slug):
        return f"/api/github/{slug}/config/"

    def test_get_resolves_workspace_over_global(self):
        """Workspace-scope row wins over the global row; an event set by
        neither falls back to DEFAULT_RULES."""
        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)

        StateTransitionConfig.objects.create(
            scope="global", rules={"pr_opened": "In Review"}
        )
        StateTransitionConfig.objects.create(
            scope="workspace", workspace=ws, rules={"pr_opened": "In Progress"}
        )

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(ws.slug))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"]["pr_opened"], "In Progress")
        self.assertEqual(resp.data["rules"]["pr_merged"], DEFAULT_RULES["pr_merged"])

    def test_get_unknown_workspace_returns_404(self):
        member = _user()
        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url("no-such-workspace"))
        self.assertEqual(resp.status_code, 404)

    def test_put_shape_only_no_state_check(self):
        """A workspace override is project-agnostic — a state NAME that does
        not exist as any State row still saves (only shape is validated)."""
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)

        self.client.force_authenticate(user=admin)
        resp = self.client.put(
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

        self.client.force_authenticate(user=admin)
        resp = self.client.put(
            self._url(ws.slug),
            {"rules": {"pr_closed_without_merge": "Done"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            StateTransitionConfig.objects.filter(scope="workspace", workspace=ws).exists()
        )

    def test_put_non_admin_403_admin_200(self):
        ws = _workspace()
        non_admin = _user()
        admin = _user()
        _wmember(ws, non_admin, role=ROLE_MEMBER)
        _wmember(ws, admin, role=ROLE_ADMIN)
        payload = {"rules": {"pr_opened": "In Progress"}}

        self.client.force_authenticate(user=non_admin)
        self.assertEqual(
            self.client.put(self._url(ws.slug), payload, format="json").status_code, 403
        )

        self.client.force_authenticate(user=admin)
        self.assertEqual(
            self.client.put(self._url(ws.slug), payload, format="json").status_code, 200
        )


# ---------------------------------------------------------------------------
# Tier 3 — per-project config  (/api/github/<slug>/projects/<id>/config/)
# ---------------------------------------------------------------------------

class GithubProjectConfigTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, slug, project_id):
        return f"/api/github/{slug}/projects/{project_id}/config/"

    def test_get_project_beats_workspace_beats_global(self):
        """Full three-tier precedence: project override > workspace override >
        global > DEFAULT_RULES, per event key."""
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

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(ws.slug, proj.id))

        self.assertEqual(resp.status_code, 200)
        # pr_opened: project wins.
        self.assertEqual(resp.data["rules"]["pr_opened"], "In Progress")
        # pr_ready_for_review: workspace wins over global (project silent).
        self.assertEqual(resp.data["rules"]["pr_ready_for_review"], "WorkspaceReview")
        # pr_merged: set by none -> DEFAULT_RULES.
        self.assertEqual(resp.data["rules"]["pr_merged"], DEFAULT_RULES["pr_merged"])

    def test_get_unknown_project_returns_404(self):
        import uuid

        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(ws.slug, uuid.uuid4()))
        self.assertEqual(resp.status_code, 404)

    def test_slug_not_owning_project_returns_404(self):
        """Cross-workspace guard: a real project_id under a DIFFERENT
        workspace's slug is a 404 — the ws-role gate can't be satisfied
        against an unrelated workspace."""
        ws_a = _workspace()
        ws_b = _workspace()
        attacker = _user()
        # attacker is an admin of ws_b, NOT ws_a.
        _wmember(ws_b, attacker, role=ROLE_ADMIN)
        proj_a = _project(ws_a, name="Secret", identifier="SEC")

        self.client.force_authenticate(user=attacker)
        resp = self.client.get(self._url(ws_b.slug, proj_a.id))
        self.assertEqual(resp.status_code, 404)

    def test_put_valid_state_name_saves_and_returns_200(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        proj = _project(ws, name="Proj2", identifier="PR2")
        _state(ws, proj, name="In Review", group="started")

        self.client.force_authenticate(user=admin)
        resp = self.client.put(
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

        self.client.force_authenticate(user=admin)
        resp = self.client.put(
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

        self.client.force_authenticate(user=admin)
        resp = self.client.put(
            self._url(ws.slug, proj.id),
            {"rules": {"pr_closed_without_merge": "Done"}},
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

        self.client.force_authenticate(user=non_admin)
        self.assertEqual(
            self.client.put(self._url(ws.slug, proj.id), payload, format="json").status_code,
            403,
        )

        self.client.force_authenticate(user=admin)
        self.assertEqual(
            self.client.put(self._url(ws.slug, proj.id), payload, format="json").status_code,
            200,
        )
