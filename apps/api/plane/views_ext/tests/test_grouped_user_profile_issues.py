# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# HTTP-level tests (real Postgres) for
# GET /api/views-ext/workspaces/<slug>/user-issues/<user_id>/.
# Mirrors test_grouped_view_issues.py's style (TransactionTestCase + explicit ORM
# rows, no mocking the unit under test), driven through rest_framework.test.APIClient.

import uuid
from datetime import date

from django.test import TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient

# Run Celery tasks inline (no broker in tests). Issue creation enqueues an ai_ext
# embedding task via a post-commit signal; eager + non-propagating means it runs
# without a broker and a failure inside it never breaks the unit under test.
# Mirrors the workload / project_ext / ai_ext / views_ext fork-app test style.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

ENDPOINT = "/api/views-ext/workspaces/{slug}/user-issues/{user_id}/"


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


def _issue(ws, proj, state, created_by, priority="none", target=None, sequence_id=1, assignees=None):
    from plane.db.models import Issue, IssueAssignee

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
    for assignee in assignees or []:
        IssueAssignee.objects.create(workspace=ws, project=proj, issue=issue, assignee=assignee)
    return issue


def _subscribe(ws, proj, issue, subscriber):
    from plane.db.models import IssueSubscriber

    return IssueSubscriber.objects.create(workspace=ws, project=proj, issue=issue, subscriber=subscriber)


class _EndpointTestCase(TransactionTestCase):
    """
    Shared fixture builder: one workspace, one project, one active member, one
    started-group state — the minimum scaffolding every test below extends. The
    "profile user" (whose assigned/created/subscribed items we're listing) is always
    `self.owner`, and requests are made by `self.owner` unless a test overrides it.
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
        self.url = ENDPOINT.format(slug=self.ws.slug, user_id=self.owner.id)


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


class InvalidParamTests(_EndpointTestCase):
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

    def test_bogus_type_returns_400_not_a_silent_union(self):
        response = self.client.get(self.url, {"type": "bogus"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)


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


class ProfileTypeTests(_EndpointTestCase):
    """
    Covers the `type=assigned|created|subscribed` selector, plus the no-`type`
    default (union of all three, byte-identical candidate pool to core's
    WorkspaceUserProfileIssuesEndpoint).
    """

    def setUp(self):
        super().setUp()
        # A second workspace member distinct from the profile owner, so
        # "created" issues (created_by=other) can be excluded from "assigned"/
        # "subscribed" results that target self.owner.
        self.other = _user()
        _wmember(self.ws, self.other, role=20)
        _pmember(self.ws, self.project, self.other, role=20)

    def test_type_assigned_returns_only_assigned_items(self):
        assigned = _issue(self.ws, self.project, self.state, self.other, assignees=[self.owner])
        _issue(self.ws, self.project, self.state, self.owner, sequence_id=2)  # created by owner, not assigned

        response = self.client.get(self.url, {"type": "assigned"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = {str(row["id"]) for row in response.data["results"]}
        self.assertEqual(result_ids, {str(assigned.id)})

    def test_type_created_returns_only_created_items(self):
        created = _issue(self.ws, self.project, self.state, self.owner)
        _issue(self.ws, self.project, self.state, self.other, sequence_id=2, assignees=[self.owner])

        response = self.client.get(self.url, {"type": "created"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = {str(row["id"]) for row in response.data["results"]}
        self.assertEqual(result_ids, {str(created.id)})

    def test_type_subscribed_returns_only_subscribed_items(self):
        subscribed = _issue(self.ws, self.project, self.state, self.other, sequence_id=3)
        _subscribe(self.ws, self.project, subscribed, self.owner)
        _issue(self.ws, self.project, self.state, self.owner, sequence_id=4)  # created, not subscribed

        response = self.client.get(self.url, {"type": "subscribed"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = {str(row["id"]) for row in response.data["results"]}
        self.assertEqual(result_ids, {str(subscribed.id)})

    def test_no_type_returns_union_of_all_three(self):
        assigned = _issue(self.ws, self.project, self.state, self.other, assignees=[self.owner])
        created = _issue(self.ws, self.project, self.state, self.owner, sequence_id=2)
        subscribed = _issue(self.ws, self.project, self.state, self.other, sequence_id=3)
        _subscribe(self.ws, self.project, subscribed, self.owner)
        unrelated = _issue(self.ws, self.project, self.state, self.other, sequence_id=4)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = {str(row["id"]) for row in response.data["results"]}
        self.assertEqual(result_ids, {str(assigned.id), str(created.id), str(subscribed.id)})
        self.assertNotIn(str(unrelated.id), result_ids)


class GuestVisibilityTests(_EndpointTestCase):
    """
    Carried across from WorkspaceUserProfileIssuesEndpoint: any active project
    member (including a guest without guest_view_all_features) can see another
    user's profile-issue list — no per-role restriction, since results are already
    scoped to issues related to `user_id`, not a full project issue list. Verified
    by test, not by reading the filter, per the D2 permission risk this task called
    out as highest-impact.
    """

    def test_active_project_member_can_view_another_users_profile_issues(self):
        guest = _user()
        _pmember(self.ws, self.project, guest, role=5)  # ROLE.GUEST, guest_view_all_features=False by default
        _wmember(self.ws, guest, role=5)

        owner_issue = _issue(self.ws, self.project, self.state, self.owner, sequence_id=2)

        guest_client = APIClient()
        guest_client.force_authenticate(user=guest)

        # Guest requests the OWNER's profile-issue list, not their own.
        response = guest_client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = {str(row["id"]) for row in response.data["results"]}
        self.assertEqual(result_ids, {str(owner_issue.id)})

    def test_non_member_forbidden(self):
        stranger = _user()
        stranger_client = APIClient()
        stranger_client.force_authenticate(user=stranger)

        response = stranger_client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_workspace_member_not_a_project_member_sees_empty_not_error(self):
        # Active WORKSPACE member (passes WorkspaceViewerPermission) who is NOT a
        # member of `self.project` — the `project__project_projectmember__member=
        # request.user` clause in the queryset itself must exclude them, returning an
        # empty list rather than a 403/500.
        non_project_member = _user()
        _wmember(self.ws, non_project_member, role=20)

        other_client = APIClient()
        other_client.force_authenticate(user=non_project_member)

        response = other_client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])
