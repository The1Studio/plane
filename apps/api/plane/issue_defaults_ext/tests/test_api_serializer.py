# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork (work-item creation defaults) — the defaults as seen through
# the PUBLIC API serializer, which is what the MCP server and both SDKs use.
#
# The field is spelled "assignees" here, not "assignee_ids". Getting that wrong
# fails silently (the creator fallback simply never fires) and every app-side
# test still passes, so the empty-list cases below are the load-bearing ones.
#
# Test matrix: plans/260824-workitem-creation-defaults/phase-4.md

import uuid
from datetime import timedelta

from crum import impersonate
from django.test import TransactionTestCase

# Run Celery tasks inline (no broker in tests).
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.api.serializers import IssueSerializer
from plane.db.models import IssueAssignee
from plane.issue_defaults_ext.defaults import local_today


def _user(user_timezone="UTC"):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    user = User.objects.create_user(
        username=f"user_{uid}", email=f"u-{uid}@test.invalid", password="x"
    )
    user.user_timezone = user_timezone
    user.save(update_fields=["user_timezone"])
    return user


def _ws(owner):
    from plane.db.models import Workspace

    slug = f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner)


def _project(ws):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
    )


def _pmember(ws, proj, user, role=15):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(
        workspace=ws, project=proj, member=user, role=role, is_active=True
    )


class _Base(TransactionTestCase):
    def setUp(self):
        self.creator = _user()
        self.ws = _ws(self.creator)
        self.project = _project(self.ws)
        _pmember(self.ws, self.project, self.creator)
        self.today = local_today(self.creator)

    def _create(self, payload, default_assignee_id=None, as_user=None):
        context = {
            "project_id": self.project.id,
            "workspace_id": self.ws.id,
            "default_assignee_id": default_assignee_id,
        }
        with impersonate(as_user or self.creator):
            serializer = IssueSerializer(data=payload, context=context)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            return serializer.save()

    def _assignee_ids(self, issue):
        return set(
            IssueAssignee.objects.filter(issue=issue).values_list(
                "assignee_id", flat=True
            )
        )


class TestPublicApiCreateDefaults(_Base):
    def test_name_only_payload_gets_creator_and_today(self):
        # This is exactly the request an MCP create_work_item call with no
        # optional arguments produces.
        issue = self._create({"name": "from mcp"})
        self.assertEqual(self._assignee_ids(issue), {self.creator.id})
        self.assertEqual(issue.target_date, self.today)

    def test_explicit_empty_assignees_stays_unassigned(self):
        issue = self._create({"name": "nobody", "assignees": []})
        self.assertEqual(self._assignee_ids(issue), set())

    def test_explicit_null_target_date_stays_empty(self):
        issue = self._create({"name": "undated", "target_date": None})
        self.assertIsNone(issue.target_date)

    def test_explicit_values_are_untouched(self):
        other = _user()
        _pmember(self.ws, self.project, other)
        issue = self._create(
            {"name": "explicit", "assignees": [other.id], "target_date": "2026-12-25"}
        )
        self.assertEqual(self._assignee_ids(issue), {other.id})
        self.assertEqual(str(issue.target_date), "2026-12-25")

    def test_project_default_assignee_wins_over_creator(self):
        lead = _user()
        _pmember(self.ws, self.project, lead)
        issue = self._create({"name": "led"}, default_assignee_id=lead.id)
        self.assertEqual(self._assignee_ids(issue), {lead.id})

    def test_future_start_date_does_not_400(self):
        future = self.today + timedelta(days=10)
        issue = self._create({"name": "later", "start_date": str(future)})
        self.assertEqual(issue.target_date, future)

    def test_creator_outside_the_project_is_not_assigned(self):
        issue = self._create({"name": "stranger"}, as_user=_user())
        self.assertEqual(self._assignee_ids(issue), set())


class TestPublicApiUpdateNeverDefaults(_Base):
    def test_clearing_a_due_date_makes_it_stay_cleared(self):
        issue = self._create({"name": "dated"})
        self.assertEqual(issue.target_date, self.today)

        with impersonate(self.creator):
            serializer = IssueSerializer(
                issue,
                data={"target_date": None},
                partial=True,
                context={
                    "project_id": self.project.id,
                    "workspace_id": self.ws.id,
                    "default_assignee_id": None,
                },
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)
            updated = serializer.save()

        updated.refresh_from_db()
        self.assertIsNone(updated.target_date)
