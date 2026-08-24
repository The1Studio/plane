# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork (work-item creation defaults) — the defaults as seen through
# IssueCreateSerializer, the path the web app, drafts, sub-work-items and epics
# all take. test_defaults.py pins the decision logic; this pins the wiring.
#
# Test matrix: plans/260824-workitem-creation-defaults/phase-3.md

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

from plane.app.serializers import IssueCreateSerializer
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


def _project(ws, default_assignee=None):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
        default_assignee=default_assignee,
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

    def _create(self, payload, extra_context=None):
        """Create through the serializer AS self.creator.

        `impersonate` sets the crum thread-local the same way the request
        middleware does in production — that is where both created_by and the
        default-resolution user come from.
        """
        context = {
            "project_id": self.project.id,
            "workspace_id": self.ws.id,
            "default_assignee_id": self.project.default_assignee_id,
        }
        context.update(extra_context or {})
        with impersonate(self.creator):
            serializer = IssueCreateSerializer(data=payload, context=context)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            return serializer.save()

    def _assignee_ids(self, issue):
        return set(
            IssueAssignee.objects.filter(issue=issue).values_list(
                "assignee_id", flat=True
            )
        )


class TestCreateDefaults(_Base):
    def test_bare_payload_gets_creator_and_today(self):
        issue = self._create({"name": "bare"})
        self.assertEqual(self._assignee_ids(issue), {self.creator.id})
        self.assertEqual(issue.target_date, self.today)

    def test_explicit_empty_assignees_stays_unassigned(self):
        issue = self._create({"name": "nobody", "assignee_ids": []})
        self.assertEqual(self._assignee_ids(issue), set())
        # ...while the due date, absent, still defaults.
        self.assertEqual(issue.target_date, self.today)

    def test_explicit_null_target_date_stays_empty(self):
        issue = self._create({"name": "undated", "target_date": None})
        self.assertIsNone(issue.target_date)
        self.assertEqual(self._assignee_ids(issue), {self.creator.id})

    def test_explicit_values_are_untouched(self):
        other = _user()
        _pmember(self.ws, self.project, other)
        issue = self._create(
            {
                "name": "explicit",
                "assignee_ids": [other.id],
                "target_date": "2026-12-25",
            }
        )
        self.assertEqual(self._assignee_ids(issue), {other.id})
        self.assertEqual(str(issue.target_date), "2026-12-25")

    def test_project_default_assignee_wins_over_creator(self):
        lead = _user()
        self.project.default_assignee = lead
        self.project.save(update_fields=["default_assignee"])
        _pmember(self.ws, self.project, lead)

        issue = self._create({"name": "led"}, {"default_assignee_id": lead.id})
        self.assertEqual(self._assignee_ids(issue), {lead.id})

    def test_future_start_date_does_not_400(self):
        # Before this change, "Start date cannot exceed target date" would have
        # rejected this payload the moment target_date defaulted to today.
        future = self.today + timedelta(days=10)
        issue = self._create({"name": "later", "start_date": str(future)})
        self.assertEqual(issue.target_date, future)

    def test_intake_opt_out_gets_neither_default(self):
        issue = self._create(
            {"name": "triaged"}, {"apply_creation_defaults": False}
        )
        self.assertEqual(self._assignee_ids(issue), set())
        self.assertIsNone(issue.target_date)

    def test_creator_outside_the_project_is_not_assigned(self):
        outsider = _user()
        with impersonate(outsider):
            serializer = IssueCreateSerializer(
                data={"name": "stranger"},
                context={
                    "project_id": self.project.id,
                    "workspace_id": self.ws.id,
                    "default_assignee_id": None,
                },
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)
            issue = serializer.save()
        self.assertEqual(self._assignee_ids(issue), set())


class TestUpdateNeverDefaults(_Base):
    """The score-20 risk: validate() runs on PATCH too."""

    def test_clearing_a_due_date_makes_it_stay_cleared(self):
        issue = self._create({"name": "dated"})
        self.assertEqual(issue.target_date, self.today)

        with impersonate(self.creator):
            serializer = IssueCreateSerializer(
                issue,
                data={"target_date": None},
                partial=True,
                context={"project_id": self.project.id},
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)
            updated = serializer.save()

        updated.refresh_from_db()
        self.assertIsNone(updated.target_date)

    def test_unrelated_patch_does_not_add_a_due_date(self):
        issue = self._create({"name": "undated", "target_date": None})

        with impersonate(self.creator):
            serializer = IssueCreateSerializer(
                issue,
                data={"name": "renamed"},
                partial=True,
                context={"project_id": self.project.id},
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)
            updated = serializer.save()

        updated.refresh_from_db()
        self.assertIsNone(updated.target_date)
        self.assertEqual(updated.name, "renamed")
