# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork (work-item creation defaults) — decision-logic tests for
# plane/issue_defaults_ext/defaults.py. Real Postgres rows (TransactionTestCase,
# mirroring cascade_ext/workload) because the assignee resolver's whole job is a
# ProjectMember lookup; mocking it would test the mock.
#
# Test matrix: plans/260824-workitem-creation-defaults/phase-2.md

import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TransactionTestCase

# Run Celery tasks inline (no broker in tests) — Issue.objects.create()
# dispatches issue activity, which otherwise fails on a refused AMQP
# connection. Same guard cascade_ext's tests use.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.db.models import Issue, IssueAssignee
from plane.issue_defaults_ext.defaults import (
    local_today,
    resolve_creation_assignee_id,
    resolve_creation_target_date,
)


# ---------------------------------------------------------------------------
# Fixtures (mirror cascade_ext/tests + workload/tests)
# ---------------------------------------------------------------------------


def _user(email=None, user_timezone="UTC"):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    user = User.objects.create_user(
        username=f"user_{uid}",
        email=email or f"u-{uid}@test.invalid",
        password="x",
    )
    user.user_timezone = user_timezone
    user.save(update_fields=["user_timezone"])
    return user


def _ws(owner=None):
    from plane.db.models import Workspace

    slug = f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(
        name=slug, slug=slug, logo="", owner=owner or _user()
    )


def _project(ws):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
    )


def _pmember(ws, proj, user, role=15, is_active=True):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(
        workspace=ws, project=proj, member=user, role=role, is_active=is_active
    )


# ---------------------------------------------------------------------------
# local_today — the timezone basis for "today" (decision D8)
# ---------------------------------------------------------------------------


class TestLocalToday(TransactionTestCase):
    def _at(self, iso_utc):
        """Freeze wall-clock at an aware UTC instant."""
        moment = datetime.fromisoformat(iso_utc).replace(tzinfo=dt_timezone.utc)
        return mock.patch(
            "plane.issue_defaults_ext.defaults.timezone.now", return_value=moment
        )

    def test_utc_user_gets_the_utc_date(self):
        user = _user(user_timezone="UTC")
        with self._at("2026-08-24T23:30:00"):
            self.assertEqual(local_today(user), date(2026, 8, 24))

    def test_utc_plus_seven_user_has_already_rolled_over(self):
        # The same instant is 06:30 on the 25th in Ho Chi Minh City. The
        # browser would have prefilled the 25th; the server must agree.
        user = _user(user_timezone="Asia/Ho_Chi_Minh")
        with self._at("2026-08-24T23:30:00"):
            self.assertEqual(local_today(user), date(2026, 8, 25))

    def test_negative_offset_user_is_still_on_the_previous_day(self):
        user = _user(user_timezone="America/Los_Angeles")
        with self._at("2026-08-25T05:00:00"):
            self.assertEqual(local_today(user), date(2026, 8, 24))

    def test_anonymous_caller_falls_back_to_utc(self):
        with self._at("2026-08-24T23:30:00"):
            self.assertEqual(local_today(None), date(2026, 8, 24))

    def test_malformed_stored_timezone_falls_back_instead_of_raising(self):
        user = _user()
        user.user_timezone = "Not/AZone"
        with self._at("2026-08-24T23:30:00"):
            self.assertEqual(local_today(user), date(2026, 8, 24))


# ---------------------------------------------------------------------------
# resolve_creation_target_date
# ---------------------------------------------------------------------------


class TestResolveCreationTargetDate(TransactionTestCase):
    def setUp(self):
        self.user = _user(user_timezone="UTC")
        self.today = local_today(self.user)

    def _resolve(self, **overrides):
        kwargs = dict(
            is_create=True,
            initial_data={},
            context={},
            start_date=None,
            user=self.user,
        )
        kwargs.update(overrides)
        return resolve_creation_target_date(**kwargs)

    def test_absent_target_date_defaults_to_today(self):
        self.assertEqual(self._resolve(), self.today)

    def test_explicit_null_is_a_deliberate_no_due_date(self):
        self.assertIsNone(self._resolve(initial_data={"target_date": None}))

    def test_explicit_date_is_left_alone(self):
        self.assertIsNone(self._resolve(initial_data={"target_date": "2026-12-01"}))

    def test_update_never_defaults(self):
        # The score-20 risk: validate() runs on PATCH too, and a user who has
        # just cleared a due date must not have it silently re-filled.
        self.assertIsNone(self._resolve(is_create=False))

    def test_opted_out_caller_never_defaults(self):
        self.assertIsNone(self._resolve(context={"apply_creation_defaults": False}))

    def test_future_start_date_wins_over_today(self):
        # Defaulting to today here would make the serializer's own
        # "Start date cannot exceed target date" check reject a request that
        # succeeds on main.
        future = self.today + timedelta(days=10)
        self.assertEqual(self._resolve(start_date=future), future)

    def test_past_start_date_still_yields_today(self):
        past = self.today - timedelta(days=10)
        self.assertEqual(self._resolve(start_date=past), self.today)

    def test_start_date_equal_to_today_yields_today(self):
        self.assertEqual(self._resolve(start_date=self.today), self.today)


# ---------------------------------------------------------------------------
# resolve_creation_assignee_id
# ---------------------------------------------------------------------------


class TestResolveCreationAssigneeId(TransactionTestCase):
    def setUp(self):
        self.creator = _user()
        self.ws = _ws(owner=self.creator)
        self.project = _project(self.ws)
        _pmember(self.ws, self.project, self.creator)

    def _resolve(self, **overrides):
        kwargs = dict(
            initial_data={},
            context={},
            project_id=self.project.id,
            default_assignee_id=None,
            created_by_id=self.creator.id,
            assignee_field="assignee_ids",
        )
        kwargs.update(overrides)
        return resolve_creation_assignee_id(**kwargs)

    # -- creator fallback --------------------------------------------------

    def test_absent_assignees_falls_back_to_the_creator(self):
        self.assertEqual(self._resolve(), self.creator.id)

    def test_explicit_empty_list_means_nobody(self):
        self.assertIsNone(self._resolve(initial_data={"assignee_ids": []}))

    def test_creator_who_is_not_a_project_member_is_skipped(self):
        outsider = _user()
        self.assertIsNone(self._resolve(created_by_id=outsider.id))

    def test_creator_below_the_role_floor_is_skipped(self):
        guest = _user()
        _pmember(self.ws, self.project, guest, role=5)
        self.assertIsNone(self._resolve(created_by_id=guest.id))

    def test_deactivated_creator_is_skipped(self):
        gone = _user()
        _pmember(self.ws, self.project, gone, is_active=False)
        self.assertIsNone(self._resolve(created_by_id=gone.id))

    def test_anonymous_creator_is_skipped(self):
        self.assertIsNone(self._resolve(created_by_id=None))

    # -- project default takes precedence ----------------------------------

    def test_project_default_wins_over_the_creator(self):
        lead = _user()
        _pmember(self.ws, self.project, lead)
        self.assertEqual(self._resolve(default_assignee_id=lead.id), lead.id)

    def test_project_default_still_applies_on_an_explicit_empty_list(self):
        # Upstream behaviour, preserved deliberately: core already assigns the
        # project default when assignee_ids is falsy. Only the NEW creator
        # fallback is gated on the field being absent.
        lead = _user()
        _pmember(self.ws, self.project, lead)
        self.assertEqual(
            self._resolve(
                default_assignee_id=lead.id, initial_data={"assignee_ids": []}
            ),
            lead.id,
        )

    def test_stale_project_default_falls_through_to_the_creator(self):
        departed = _user()  # never a member of this project
        self.assertEqual(
            self._resolve(default_assignee_id=departed.id), self.creator.id
        )

    def test_stale_project_default_with_explicit_empty_list_means_nobody(self):
        departed = _user()
        self.assertIsNone(
            self._resolve(
                default_assignee_id=departed.id, initial_data={"assignee_ids": []}
            )
        )

    # -- opt-out and field naming ------------------------------------------

    def test_opted_out_caller_never_defaults(self):
        self.assertIsNone(self._resolve(context={"apply_creation_defaults": False}))

    def test_public_api_field_name_behaves_identically(self):
        # The public API spells the field "assignees". Passing the wrong name
        # fails silently — the fallback simply never fires — so both spellings
        # are pinned here.
        self.assertEqual(self._resolve(assignee_field="assignees"), self.creator.id)
        self.assertIsNone(
            self._resolve(
                assignee_field="assignees", initial_data={"assignees": []}
            )
        )

    def test_app_field_name_is_not_consulted_for_the_api_spelling(self):
        # An "assignees" payload must not be read through the app serializer's
        # field name, or an API client's explicit [] would be missed.
        self.assertEqual(
            self._resolve(
                assignee_field="assignee_ids", initial_data={"assignees": []}
            ),
            self.creator.id,
        )


# ---------------------------------------------------------------------------
# Bulk-import exclusion (decision D6) — costs no code, so it is pinned here
# ---------------------------------------------------------------------------


class TestRawOrmWritersAreExcluded(TransactionTestCase):
    def test_orm_create_gets_neither_default(self):
        # The ClickUp loaders write through Issue.objects.create(), never a
        # serializer, so the defaults cannot reach them. If someone later moves
        # this logic into a model signal, this test goes red — which is the
        # point: a signal WOULD stamp today's due date on every migrated issue.
        creator = _user()
        ws = _ws(owner=creator)
        project = _project(ws)
        _pmember(ws, project, creator)

        issue = Issue.objects.create(
            workspace=ws,
            project=project,
            name="migrated",
            created_by=creator,
            sequence_id=1,
        )

        self.assertIsNone(issue.target_date)
        self.assertFalse(IssueAssignee.objects.filter(issue=issue).exists())
