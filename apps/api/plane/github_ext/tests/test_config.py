# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P2 — status-automation config CRUD tests (views/config.py).
#
# TransactionTestCase (mirrors test_webhook.py style), real Postgres, no
# mocking of the unit under test. Permission-layer auth is exercised via
# DRF's `APIClient.force_authenticate` (see
# workload/tests/test_workload_bulk.py TestBulkEstimatesHTTP — the existing
# precedent for hitting an `@allow_permission(level="WORKSPACE")`-gated
# BaseAPIView end-to-end): `force_authenticate` bypasses
# `authentication_classes` (BaseSessionAuthentication) entirely and sets
# `request.user` directly, so the ADMIN-vs-MEMBER distinction is enforced
# for real by `@allow_permission`'s own `WorkspaceMember.objects.filter(...,
# role__in=..., is_active=True)` lookup — not by the test double.

from django.test import TransactionTestCase
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


class GithubProjectConfigTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, project_id):
        return f"/api/github/projects/{project_id}/config/"

    # -- GET / resolve precedence -----------------------------------------

    def test_get_project_override_beats_global(self):
        """A project-scope row wins over the global row for a shared event
        key; a key absent from both rows falls back to DEFAULT_RULES."""
        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)
        proj = _project(ws, name="Proj", identifier="PRJ")
        _state(ws, proj, name="In Review", group="started")
        _state(ws, proj, name="In Progress", group="started")

        StateTransitionConfig.objects.create(
            scope="global", rules={"pr_opened": "In Review"}
        )
        StateTransitionConfig.objects.create(
            scope="project", project=proj, rules={"pr_opened": "In Progress"}
        )

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(proj.id))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"]["pr_opened"], "In Progress")
        # pr_merged was set by neither row -> DEFAULT_RULES fallback.
        self.assertEqual(resp.data["rules"]["pr_merged"], DEFAULT_RULES["pr_merged"])

    def test_get_unknown_project_returns_404(self):
        import uuid

        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(uuid.uuid4()))

        self.assertEqual(resp.status_code, 404)

    # -- PUT validation ------------------------------------------------------

    def test_put_valid_state_name_saves_and_returns_200(self):
        ws = _workspace()
        admin = _user()
        _wmember(ws, admin, role=ROLE_ADMIN)
        proj = _project(ws, name="Proj2", identifier="PR2")
        _state(ws, proj, name="In Review", group="started")

        self.client.force_authenticate(user=admin)
        resp = self.client.put(
            self._url(proj.id),
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
        # No matching State row created.

        self.client.force_authenticate(user=admin)
        resp = self.client.put(
            self._url(proj.id),
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
            self._url(proj.id),
            {"rules": {"pr_closed_without_merge": "Done"}},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            StateTransitionConfig.objects.filter(scope="project", project=proj).exists()
        )

    # -- Admin-only gate -------------------------------------------------

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
        resp_denied = self.client.put(self._url(proj.id), payload, format="json")
        self.assertEqual(resp_denied.status_code, 403)
        self.assertFalse(
            StateTransitionConfig.objects.filter(scope="project", project=proj).exists()
        )

        self.client.force_authenticate(user=admin)
        resp_ok = self.client.put(self._url(proj.id), payload, format="json")
        self.assertEqual(resp_ok.status_code, 200)
        self.assertTrue(
            StateTransitionConfig.objects.filter(scope="project", project=proj).exists()
        )


class GithubGlobalConfigTests(TransactionTestCase):
    """Smoke coverage for the global-scope endpoint's ?slug= resolution +
    admin gate (see views/config.py module docstring for why ?slug= exists
    on a route with no <slug> path segment)."""

    def setUp(self):
        self.client = APIClient()

    def test_get_missing_slug_returns_400(self):
        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)

        self.client.force_authenticate(user=member)
        resp = self.client.get("/api/github/config/")

        self.assertEqual(resp.status_code, 400)

    def test_get_returns_defaults_when_no_row(self):
        ws = _workspace()
        member = _user()
        _wmember(ws, member, role=ROLE_MEMBER)

        self.client.force_authenticate(user=member)
        resp = self.client.get(f"/api/github/config/?slug={ws.slug}")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rules"], DEFAULT_RULES)

    def test_put_non_admin_403_admin_200_and_validates(self):
        ws = _workspace()
        non_admin = _user()
        admin = _user()
        _wmember(ws, non_admin, role=ROLE_MEMBER)
        _wmember(ws, admin, role=ROLE_ADMIN)

        self.client.force_authenticate(user=non_admin)
        resp_denied = self.client.put(
            "/api/github/config/",
            {"slug": ws.slug, "rules": {"pr_opened": "In Progress"}},
            format="json",
        )
        self.assertEqual(resp_denied.status_code, 403)

        self.client.force_authenticate(user=admin)
        resp_bad_key = self.client.put(
            "/api/github/config/",
            {"slug": ws.slug, "rules": {"not_a_real_event": "In Progress"}},
            format="json",
        )
        self.assertEqual(resp_bad_key.status_code, 400)

        resp_ok = self.client.put(
            "/api/github/config/",
            {"slug": ws.slug, "rules": {"pr_opened": "In Progress"}},
            format="json",
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertEqual(resp_ok.data["rules"], {"pr_opened": "In Progress"})
        row = StateTransitionConfig.objects.get(scope="global")
        self.assertEqual(row.rules, {"pr_opened": "In Progress"})
