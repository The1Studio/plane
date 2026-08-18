# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# HTTP-level tests (real Postgres) for GET /api/views-ext/workspaces/<slug>/issues/.
# Mirrors the project_ext / workload test style (TransactionTestCase + explicit ORM
# rows, no mocking the unit under test) but drives the endpoint through
# rest_framework.test.APIClient since this app's success criteria are about
# request/response HTTP behaviour, not a pure service function.

import uuid
from datetime import date

from django.test import TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient

# Run Celery tasks inline (no broker in tests). Issue creation enqueues an ai_ext
# embedding task via a post-commit signal; eager + non-propagating means it runs
# without a broker and a failure inside it never breaks the unit under test.
# Mirrors the workload / project_ext / ai_ext fork-app test style.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

ENDPOINT = "/api/views-ext/workspaces/{slug}/issues/"


def _user(email=None):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    email = email or f"u-{uid}@test.invalid"
    return User.objects.create_user(username=f"user_{uid}", email=email, password="x")


def _ws(slug=None, owner=None):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    owner = owner or _user()
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner)


def _wmember(ws, user, role=15, is_active=True):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(workspace=ws, member=user, role=role, is_active=is_active)


def _project(ws, guest_view_all_features=False):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
        guest_view_all_features=guest_view_all_features,
    )


def _pmember(ws, proj, user, role=15, is_active=True):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(workspace=ws, project=proj, member=user, role=role, is_active=is_active)


def _state(ws, proj, group):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws,
        project=proj,
        name=f"{group}-{uuid.uuid4().hex[:4]}",
        color="#fff",
        group=group,
    )


def _issue(ws, proj, state, created_by, priority="none", target=None, sequence_id=1):
    from plane.db.models import Issue

    # BaseModel.save() auto-sets created_by from crum's thread-local current user
    # (set by request middleware) and silently overwrites any created_by passed to
    # .objects.create() when no request context is active, i.e. every plain-ORM
    # test fixture. Force it explicitly via the save() kwarg it documents instead.
    issue = Issue(
        workspace=ws,
        project=proj,
        name=f"i-{uuid.uuid4().hex[:6]}",
        state=state,
        priority=priority,
        target_date=target,
        sequence_id=sequence_id,
    )
    issue.save(created_by_id=created_by.id)
    return issue


class _EndpointTestCase(TransactionTestCase):
    """
    Shared fixture builder: one workspace, one project, one active member, one
    started-group state — the minimum scaffolding every test below extends.
    """

    def setUp(self):
        self.owner = _user()
        self.ws = _ws(owner=self.owner)
        _wmember(self.ws, self.owner, role=20)
        self.project = _project(self.ws)
        _pmember(self.ws, self.project, self.owner, role=20)
        self.state = _state(self.ws, self.project, "started")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.url = ENDPOINT.format(slug=self.ws.slug)


class UngroupedResponseShapeTests(_EndpointTestCase):
    def test_no_group_by_returns_flat_list_and_null_grouped_by(self):
        _issue(self.ws, self.project, self.state, self.owner)
        _issue(self.ws, self.project, self.state, self.owner, sequence_id=2)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["grouped_by"])
        self.assertIsInstance(response.data["results"], list)
        self.assertEqual(len(response.data["results"]), 2)


class GroupedResponseShapeTests(_EndpointTestCase):
    def test_group_by_priority_returns_dict_keyed_by_priority(self):
        _issue(self.ws, self.project, self.state, self.owner, priority="urgent")
        _issue(self.ws, self.project, self.state, self.owner, priority="high", sequence_id=2)

        response = self.client.get(self.url, {"group_by": "priority"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["grouped_by"], "priority")
        self.assertIsInstance(response.data["results"], dict)
        self.assertIn("urgent", response.data["results"])
        self.assertIn("high", response.data["results"])
        # Each group wraps as {"results": [...], "total_results": N} — the paginator's
        # own process_results() shape (same as WorkspaceUserProfileIssuesEndpoint),
        # not a bare list per group key.
        self.assertEqual(len(response.data["results"]["urgent"]["results"]), 1)

    def test_group_by_and_sub_group_by_returns_sub_grouped_shape(self):
        other_project = _project(self.ws)
        _pmember(self.ws, other_project, self.owner, role=20)
        other_state = _state(self.ws, other_project, "started")

        _issue(self.ws, self.project, self.state, self.owner)
        _issue(self.ws, other_project, other_state, self.owner, sequence_id=2)

        response = self.client.get(self.url, {"group_by": "state__group", "sub_group_by": "project_id"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["grouped_by"], "state__group")
        self.assertEqual(response.data["sub_grouped_by"], "project_id")
        self.assertIsInstance(response.data["results"], dict)
        self.assertIn("started", response.data["results"])
        self.assertIsInstance(response.data["results"]["started"], dict)
        # Sub-grouped shape nests one level deeper: group -> {"results": {subgroup:
        # {"results": [...], "total_results": N}}, "total_results": N}.
        self.assertIn(str(self.project.id), response.data["results"]["started"]["results"])
        self.assertIn(str(other_project.id), response.data["results"]["started"]["results"])


class InvalidGroupByTests(_EndpointTestCase):
    def test_bogus_group_by_returns_400_not_a_flat_list(self):
        _issue(self.ws, self.project, self.state, self.owner)

        response = self.client.get(self.url, {"group_by": "bogus"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_bogus_sub_group_by_returns_400(self):
        response = self.client.get(self.url, {"group_by": "priority", "sub_group_by": "bogus"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_same_group_by_and_sub_group_by_returns_400(self):
        response = self.client.get(self.url, {"group_by": "priority", "sub_group_by": "priority"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sub_group_by_without_group_by_returns_400(self):
        response = self.client.get(self.url, {"sub_group_by": "priority"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_malformed_before_returns_400(self):
        response = self.client.get(self.url, {"before": "not-a-date"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class DateRangeTests(_EndpointTestCase):
    def test_before_after_narrows_by_target_date(self):
        _issue(self.ws, self.project, self.state, self.owner, target=date(2026, 1, 5))
        _issue(self.ws, self.project, self.state, self.owner, target=date(2026, 6, 15), sequence_id=2)
        _issue(self.ws, self.project, self.state, self.owner, target=date(2026, 12, 20), sequence_id=3)

        response = self.client.get(self.url, {"after": "2026-06-01", "before": "2026-06-30"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        # response.data holds native Python objects pre-render (a `date`, not a str)
        self.assertEqual(response.data["results"][0]["target_date"], date(2026, 6, 15))


class GuestVisibilityTests(_EndpointTestCase):
    """
    D2's highest-impact risk: `_get_project_permission_filters` must keep a guest
    without `guest_view_all_features` from seeing issues they did not create — the
    grouped endpoint must not leak issue titles through group counts either.
    """

    def test_guest_without_view_all_features_sees_only_own_created_items(self):
        guest = _user()
        _pmember(self.ws, self.project, guest, role=5)  # ROLE.GUEST, project defaults guest_view_all_features=False
        _wmember(self.ws, guest, role=5)

        own_issue = _issue(self.ws, self.project, self.state, guest, sequence_id=2)
        _issue(self.ws, self.project, self.state, self.owner, sequence_id=3)  # not created by guest

        guest_client = APIClient()
        guest_client.force_authenticate(user=guest)

        response = guest_client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # response.data holds native UUID objects pre-render — stringify to compare
        result_ids = {str(row["id"]) for row in response.data["results"]}
        self.assertEqual(result_ids, {str(own_issue.id)})

    def test_guest_with_view_all_features_sees_all_project_items(self):
        open_project = _project(self.ws, guest_view_all_features=True)
        guest = _user()
        _pmember(self.ws, open_project, guest, role=5)
        _wmember(self.ws, guest, role=5)
        open_state = _state(self.ws, open_project, "started")

        issue_a = _issue(self.ws, open_project, open_state, self.owner, sequence_id=4)
        issue_b = _issue(self.ws, open_project, open_state, guest, sequence_id=5)

        guest_client = APIClient()
        guest_client.force_authenticate(user=guest)

        response = guest_client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # response.data holds native UUID objects pre-render — stringify to compare
        result_ids = {str(row["id"]) for row in response.data["results"]}
        self.assertEqual(result_ids, {str(issue_a.id), str(issue_b.id)})

    def test_non_member_forbidden(self):
        stranger = _user()
        stranger_client = APIClient()
        stranger_client.force_authenticate(user=stranger)

        response = stranger_client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class FrontendEmittedGroupByTests(_EndpointTestCase):
    """
    Regression guard for the 2026-08-18 production incident.

    The allowlist originally held only the four values D3 recommended the UI *offer*
    (state__group / priority / project_id / labels__id). But the frontend emits the full
    EIssueGroupByToServerOptions range: a display filter persisted from the Work Items tab
    sends group_by=state_id, and the Calendar layout always sends group_by=target_date.
    Both 400'd on every request, so List and Board never rendered and Calendar silently
    fell back to ungrouped -- which read as "slow" rather than "broken".

    Every value this enum can emit must be accepted. Assert them all, so adding a layout
    or a group-by option upstream cannot reintroduce this silently.
    """

    FRONTEND_EMITTED = [
        "state_id",
        "state__group",
        "priority",
        "labels__id",
        "assignees__id",
        "cycle_id",
        "issue_module__module_id",
        "target_date",
        "project_id",
        "created_by",
    ]

    def test_every_frontend_emitted_group_by_is_accepted(self):
        _issue(self.ws, self.project, self.state, self.owner)

        for field in self.FRONTEND_EMITTED:
            with self.subTest(group_by=field):
                response = self.client.get(self.url, {"group_by": field})
                self.assertEqual(
                    response.status_code,
                    status.HTTP_200_OK,
                    msg=f"group_by={field} must be accepted; the frontend emits it",
                )
                self.assertEqual(response.data["grouped_by"], field)
                self.assertIsInstance(response.data["results"], dict)
