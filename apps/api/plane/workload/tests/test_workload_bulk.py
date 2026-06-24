# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Integration tests for the bulk estimates endpoint and service function.
# Mirrors the existing test_workload_db.py style: TransactionTestCase +
# explicit ORM rows, factory-boy-style helpers, real Postgres, no mocking
# the unit under test.

import uuid

from django.test import SimpleTestCase, TransactionTestCase
from rest_framework.test import APIClient

# Run Celery tasks inline (no broker in tests).
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.service import BULK_ESTIMATES_CAP, BulkEstimatesError, bulk_estimates


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_workload_db.py so the two files stay in sync)
# ---------------------------------------------------------------------------

def _ws(slug=None):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    owner = _user()
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner)


def _user(email=None, is_bot=False):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    email = email or f"u-{uid}@test.invalid"
    return User.objects.create_user(
        username=f"user_{uid}", email=email, password="x", is_bot=is_bot
    )


def _project(ws, guest_view_all=False):
    from plane.db.models import Project

    proj = Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
    )
    if guest_view_all:
        proj.guest_view_all_features = True
        proj.save()
    return proj


def _pmember(ws, proj, user, role=15, is_active=True):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(
        workspace=ws, project=proj, member=user, role=role, is_active=is_active
    )


def _wmember(ws, user, role=20):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(
        workspace=ws, member=user, role=role, is_active=True
    )


def _state(ws, proj, group="started"):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws,
        project=proj,
        name=f"{group}-{uuid.uuid4().hex[:4]}",
        color="#fff",
        group=group,
    )


def _issue(ws, proj, state, created_by):
    from plane.db.models import Issue

    return Issue.objects.create(
        workspace=ws,
        project=proj,
        name=f"i-{uuid.uuid4().hex[:6]}",
        created_by=created_by,
        state=state,
        sequence_id=1,
    )


def _assign(ws, proj, issue, user):
    from plane.db.models import IssueAssignee

    return IssueAssignee.objects.create(
        workspace=ws, project=proj, issue=issue, assignee=user
    )


def _estimate(ws, proj, issue, hours):
    from plane.workload.models import WorkloadEstimate

    return WorkloadEstimate.objects.create(
        workspace=ws, project=proj, issue=issue, hours=hours
    )


# ---------------------------------------------------------------------------
# Service-layer tests (no HTTP)
# ---------------------------------------------------------------------------

class TestBulkEstimatesHappyPath(TransactionTestCase):
    def test_returns_estimates_for_in_scope_issues(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj)
        i1 = _issue(ws, proj, st, user)
        i2 = _issue(ws, proj, st, user)
        _estimate(ws, proj, i1, 3.5)
        _estimate(ws, proj, i2, 8.0)

        result = bulk_estimates(user, ws.slug, [i1.id, i2.id])

        self.assertEqual(result, {str(i1.id): 3.5, str(i2.id): 8.0})

    def test_missing_issue_omitted(self):
        """An issue_id with no estimate row is simply absent from the result."""
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj)
        i1 = _issue(ws, proj, st, user)
        i_no_est = _issue(ws, proj, st, user)
        _estimate(ws, proj, i1, 5.0)
        phantom_id = uuid.uuid4()

        result = bulk_estimates(user, ws.slug, [i1.id, i_no_est.id, phantom_id])

        self.assertIn(str(i1.id), result)
        self.assertNotIn(str(i_no_est.id), result)
        self.assertNotIn(str(phantom_id), result)

    def test_stored_zero_is_returned_not_omitted(self):
        """hours == 0 rows must be returned; grid distinguishes "no estimate"
        (absent key) from "explicitly set to 0" (key present, value 0)."""
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj)
        issue = _issue(ws, proj, st, user)
        _estimate(ws, proj, issue, 0.0)

        result = bulk_estimates(user, ws.slug, [issue.id])

        self.assertIn(str(issue.id), result)
        self.assertEqual(result[str(issue.id)], 0.0)


class TestBulkEstimatesValidation(TransactionTestCase):
    def test_empty_issue_ids_raises_bulk_estimates_error(self):
        """Empty list → BulkEstimatesError (NOT bare ValueError — Fix 1)."""
        ws = _ws()
        user = _user()
        _wmember(ws, user)

        with self.assertRaises(BulkEstimatesError) as ctx:
            bulk_estimates(user, ws.slug, [])
        self.assertIn("empty", str(ctx.exception).lower())

    def test_cap_exceeded_raises_bulk_estimates_error(self):
        """Oversize list → BulkEstimatesError (NOT bare ValueError — Fix 1)."""
        ws = _ws()
        user = _user()
        _wmember(ws, user)
        oversized = [uuid.uuid4() for _ in range(BULK_ESTIMATES_CAP + 1)]

        with self.assertRaises(BulkEstimatesError) as ctx:
            bulk_estimates(user, ws.slug, oversized)
        self.assertIn(str(BULK_ESTIMATES_CAP), str(ctx.exception))

    def test_exactly_cap_size_does_not_raise(self):
        """The cap boundary is exclusive: len == cap is allowed."""
        ws = _ws()
        user = _user()
        _wmember(ws, user)
        at_cap = [uuid.uuid4() for _ in range(BULK_ESTIMATES_CAP)]

        # No exception; result is empty because none of these ids have rows.
        result = bulk_estimates(user, ws.slug, at_cap)
        self.assertEqual(result, {})


class TestBulkEstimatesCrossProjectIsolation(TransactionTestCase):
    def test_member_of_project_a_cannot_read_project_b_estimates(self):
        """Cross-project isolation: member of A requests B's issue_ids → B omitted."""
        ws = _ws()
        proj_a = _project(ws)
        proj_b = _project(ws)
        user_a = _user()
        user_b = _user()
        _pmember(ws, proj_a, user_a)  # user_a is NOT a member of proj_b
        _pmember(ws, proj_b, user_b)

        st_b = _state(ws, proj_b)
        issue_b = _issue(ws, proj_b, st_b, user_b)
        _estimate(ws, proj_b, issue_b, 10.0)

        result = bulk_estimates(user_a, ws.slug, [issue_b.id])

        # proj_b's issue must not appear
        self.assertNotIn(str(issue_b.id), result)

    def test_member_of_both_sees_both(self):
        ws = _ws()
        proj_a = _project(ws)
        proj_b = _project(ws)
        user = _user()
        _pmember(ws, proj_a, user)
        _pmember(ws, proj_b, user)
        st_a = _state(ws, proj_a)
        st_b = _state(ws, proj_b)
        i_a = _issue(ws, proj_a, st_a, user)
        i_b = _issue(ws, proj_b, st_b, user)
        _estimate(ws, proj_a, i_a, 3.0)
        _estimate(ws, proj_b, i_b, 7.0)

        result = bulk_estimates(user, ws.slug, [i_a.id, i_b.id])

        self.assertEqual(result, {str(i_a.id): 3.0, str(i_b.id): 7.0})

    def test_workspace_admin_sees_all_projects(self):
        ws = _ws()
        proj_a = _project(ws)
        proj_b = _project(ws)
        admin = _user()
        _wmember(ws, admin, role=20)  # workspace admin, no ProjectMember rows
        other = _user()
        _pmember(ws, proj_a, other)
        _pmember(ws, proj_b, other)
        st_a = _state(ws, proj_a)
        st_b = _state(ws, proj_b)
        i_a = _issue(ws, proj_a, st_a, other)
        i_b = _issue(ws, proj_b, st_b, other)
        _estimate(ws, proj_a, i_a, 2.0)
        _estimate(ws, proj_b, i_b, 4.0)

        result = bulk_estimates(admin, ws.slug, [i_a.id, i_b.id])

        self.assertIn(str(i_a.id), result)
        self.assertIn(str(i_b.id), result)


class TestBulkEstimatesGuestRestriction(TransactionTestCase):
    def test_flag_off_guest_sees_only_assigned_issues(self):
        """Flag-off guest (guest_view_all_features=False) gets only issues
        assigned to them — mirrors the per-issue gate in estimate_get."""
        ws = _ws()
        proj = _project(ws)  # guest_view_all_features defaults to False
        guest = _user()
        other = _user()
        _pmember(ws, proj, guest, role=5)
        _pmember(ws, proj, other, role=15)

        st = _state(ws, proj)
        i_self = _issue(ws, proj, st, guest)
        i_other = _issue(ws, proj, st, other)
        _assign(ws, proj, i_self, guest)   # guest is assigned to i_self
        # guest is NOT assigned to i_other
        _estimate(ws, proj, i_self, 3.0)
        _estimate(ws, proj, i_other, 9.0)

        result = bulk_estimates(guest, ws.slug, [i_self.id, i_other.id])

        self.assertIn(str(i_self.id), result)
        self.assertNotIn(str(i_other.id), result)

    def test_flag_on_guest_sees_all(self):
        """guest_view_all_features=True: guest sees the whole project."""
        ws = _ws()
        proj = _project(ws, guest_view_all=True)
        guest = _user()
        other = _user()
        _pmember(ws, proj, guest, role=5)
        _pmember(ws, proj, other, role=15)

        st = _state(ws, proj)
        i_self = _issue(ws, proj, st, guest)
        i_other = _issue(ws, proj, st, other)
        _estimate(ws, proj, i_self, 3.0)
        _estimate(ws, proj, i_other, 9.0)

        result = bulk_estimates(guest, ws.slug, [i_self.id, i_other.id])

        self.assertIn(str(i_self.id), result)
        self.assertIn(str(i_other.id), result)

    def test_no_scope_returns_empty(self):
        """User with no project memberships gets an empty result."""
        ws = _ws()
        user = _user()
        _wmember(ws, user, role=10)  # workspace member, no project memberships

        some_id = uuid.uuid4()
        result = bulk_estimates(user, ws.slug, [some_id])

        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# URL routing tests (no DB)
# ---------------------------------------------------------------------------

class TestBulkEstimatesRouting(SimpleTestCase):
    def test_app_api_bulk_route_resolves(self):
        from django.urls import resolve

        from plane.workload.views import WorkloadEstimatesBulkEndpoint

        match = resolve("/api/workspaces/acme/workload-estimates/")
        self.assertEqual(match.func.view_class, WorkloadEstimatesBulkEndpoint)

    def test_public_api_bulk_route_resolves(self):
        from django.urls import resolve

        from plane.workload.api_views import WorkloadEstimatesBulkAPIEndpoint

        match = resolve("/api/v1/workspaces/acme/workload-estimates/")
        self.assertEqual(match.func.view_class, WorkloadEstimatesBulkAPIEndpoint)


# ---------------------------------------------------------------------------
# HTTP-layer tests — view handler + @allow_permission decorator (Fix 2)
# Uses DRF APIClient with force_authenticate to exercise the full request
# path: URL dispatch → @allow_permission → estimate_bulk → service.
# ---------------------------------------------------------------------------

class TestBulkEstimatesHTTP(TransactionTestCase):
    """Exercises the view handler and the @allow_permission decorator gate."""

    def setUp(self):
        self.client = APIClient()

    def _url(self, slug, **params):
        """Build /api/workspaces/<slug>/workload-estimates/?k=v URL."""
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"/api/workspaces/{slug}/workload-estimates/"
        return f"{url}?{qs}" if qs else url

    def test_403_for_non_member(self):
        """A user not in the workspace gets 403 from @allow_permission."""
        ws = _ws()
        outsider = _user()
        # outsider has NO WorkspaceMember row
        self.client.force_authenticate(user=outsider)

        some_id = uuid.uuid4()
        resp = self.client.get(self._url(ws.slug, issue_ids=str(some_id)))

        self.assertEqual(resp.status_code, 403)

    def test_400_empty_issue_ids_via_endpoint(self):
        """Empty issue_ids query param → 400 from the view handler."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        resp = self.client.get(self._url(ws.slug, issue_ids=""))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_400_oversize_issue_ids_via_endpoint(self):
        """issue_ids list exceeding the cap → 400 from the view handler."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        many_ids = ",".join(str(uuid.uuid4()) for _ in range(BULK_ESTIMATES_CAP + 1))
        resp = self.client.get(self._url(ws.slug, issue_ids=many_ids))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_400_all_garbage_ids_via_endpoint(self):
        """All non-UUID tokens parse to an empty list → 400."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        resp = self.client.get(self._url(ws.slug, issue_ids="not-a-uuid,also-bad"))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_200_correct_body_for_workspace_member(self):
        """Workspace member gets 200 with {issue_id: hours} body."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        proj = _project(ws)
        _pmember(ws, proj, member)
        st = _state(ws, proj)
        issue = _issue(ws, proj, st, member)
        _estimate(ws, proj, issue, 4.5)

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(ws.slug, issue_ids=str(issue.id)))

        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(issue.id), resp.data)
        self.assertEqual(resp.data[str(issue.id)], 4.5)

    def test_200_missing_issue_absent_from_body(self):
        """Issue with no estimate row is omitted from the 200 response body."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        proj = _project(ws)
        _pmember(ws, proj, member)
        st = _state(ws, proj)
        issue_no_est = _issue(ws, proj, st, member)

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(ws.slug, issue_ids=str(issue_no_est.id)))

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(str(issue_no_est.id), resp.data)

    def test_200_stored_zero_in_body(self):
        """hours == 0 must appear in the response body, not be silently dropped."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        proj = _project(ws)
        _pmember(ws, proj, member)
        st = _state(ws, proj)
        issue = _issue(ws, proj, st, member)
        _estimate(ws, proj, issue, 0.0)

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(ws.slug, issue_ids=str(issue.id)))

        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(issue.id), resp.data)
        self.assertEqual(resp.data[str(issue.id)], 0.0)
