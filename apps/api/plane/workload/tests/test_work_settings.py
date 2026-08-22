# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Tests for WorkloadSettings: model constraints, serializer validation, and
# the /work-settings/ endpoint (app API + public API). Mirrors the existing
# test_workload_bulk.py style: TransactionTestCase + explicit ORM rows, real
# Postgres, no mocking the unit under test.

import uuid

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import resolve
from rest_framework.test import APIClient

# Run Celery tasks inline (no broker in tests).
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.constants import DEFAULT_MAX_DAILY_HOURS, DEFAULT_WEEK_START_DAY, DEFAULT_WORKDAYS
from plane.workload.models import WorkloadSettings
from plane.workload.serializers import WorkloadSettingsSerializer


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_workload_db.py / test_workload_bulk.py so the
# files stay in sync)
# ---------------------------------------------------------------------------

def _ws(slug=None):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    owner = _user()
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner)


def _user(email=None):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    email = email or f"u-{uid}@test.invalid"
    return User.objects.create_user(username=f"user_{uid}", email=email, password="x")


def _wmember(ws, user, role=20):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(workspace=ws, member=user, role=role, is_active=True)


# ---------------------------------------------------------------------------
# Model-level constraint tests
# ---------------------------------------------------------------------------

class TestWorkloadSettingsModelDefaults(TransactionTestCase):
    def test_default_workdays_is_mon_fri_and_not_shared_across_instances(self):
        """default_workdays() must return a FRESH list per call — a shared
        mutable-default list would let mutating one row's workdays leak into
        another instance's unsaved default."""
        ws1 = _ws()
        ws2 = _ws()
        s1 = WorkloadSettings.objects.create(workspace=ws1)
        s2 = WorkloadSettings.objects.create(workspace=ws2)

        self.assertEqual(s1.workdays, [1, 2, 3, 4, 5])
        s1.workdays.append(6)
        s1.save()
        s2.refresh_from_db()
        self.assertEqual(s2.workdays, [1, 2, 3, 4, 5])  # unaffected by s1's mutation

    def test_defaults_match_constants(self):
        ws = _ws()
        obj = WorkloadSettings.objects.create(workspace=ws)
        self.assertEqual(obj.max_daily_hours, DEFAULT_MAX_DAILY_HOURS)
        self.assertEqual(obj.workdays, DEFAULT_WORKDAYS)
        self.assertEqual(obj.week_start_day, DEFAULT_WEEK_START_DAY)


class TestWorkloadSettingsModelConstraints(TransactionTestCase):
    def test_empty_workdays_violates_check_constraint(self):
        ws = _ws()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkloadSettings.objects.create(workspace=ws, workdays=[])

    def test_week_start_day_out_of_range_violates_check_constraint(self):
        ws = _ws()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkloadSettings.objects.create(workspace=ws, week_start_day=7)

    def test_one_row_per_workspace(self):
        ws = _ws()
        WorkloadSettings.objects.create(workspace=ws)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkloadSettings.objects.create(workspace=ws)


# ---------------------------------------------------------------------------
# Serializer validation tests
# ---------------------------------------------------------------------------

class TestWorkloadSettingsSerializer(SimpleTestCase):
    def _valid_payload(self, **overrides):
        payload = {"max_daily_hours": 8.0, "workdays": [1, 2, 3, 4, 5], "week_start_day": 1}
        payload.update(overrides)
        return payload

    def test_valid_payload_is_accepted(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload())
        self.assertTrue(s.is_valid(), s.errors)

    def test_response_shape_is_exactly_the_pinned_contract(self):
        """plan.md pins the wire shape to exactly these 3 keys — no
        id/workspace/timestamps leak into the payload."""
        s = WorkloadSettingsSerializer(data=self._valid_payload())
        s.is_valid(raise_exception=True)
        self.assertEqual(set(s.validated_data.keys()), {"max_daily_hours", "workdays", "week_start_day"})

    def test_empty_workdays_rejected(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(workdays=[]))
        self.assertFalse(s.is_valid())
        self.assertIn("workdays", s.errors)

    def test_workdays_out_of_range_rejected(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(workdays=[1, 7]))
        self.assertFalse(s.is_valid())
        self.assertIn("workdays", s.errors)

    def test_workdays_duplicate_rejected(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(workdays=[1, 1, 2]))
        self.assertFalse(s.is_valid())
        self.assertIn("workdays", s.errors)

    def test_workdays_normalized_to_ascending_order(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(workdays=[5, 1, 3]))
        s.is_valid(raise_exception=True)
        self.assertEqual(s.validated_data["workdays"], [1, 3, 5])

    def test_week_start_day_out_of_range_rejected(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(week_start_day=7))
        self.assertFalse(s.is_valid())
        self.assertIn("week_start_day", s.errors)

    def test_negative_max_daily_hours_rejected(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(max_daily_hours=-1))
        self.assertFalse(s.is_valid())
        self.assertIn("max_daily_hours", s.errors)

    def test_max_daily_hours_over_cap_rejected(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(max_daily_hours=10001))
        self.assertFalse(s.is_valid())
        self.assertIn("max_daily_hours", s.errors)

    def test_max_daily_hours_quantized(self):
        s = WorkloadSettingsSerializer(data=self._valid_payload(max_daily_hours=8.126))
        s.is_valid(raise_exception=True)
        self.assertEqual(s.validated_data["max_daily_hours"], 8.13)

    def test_old_max_weekly_hours_key_rejected_no_alias(self):
        """D2 (plan.md) — no backward-compat alias: a payload carrying the
        retired weekly key (even alongside a valid daily one) is rejected,
        not silently ignored."""
        payload = {"max_weekly_hours": 8.0, "workdays": [1, 2, 3, 4, 5], "week_start_day": 1}
        s = WorkloadSettingsSerializer(data=payload)
        self.assertFalse(s.is_valid())
        self.assertIn("max_weekly_hours", s.errors)


# ---------------------------------------------------------------------------
# Routing tests (no DB)
# ---------------------------------------------------------------------------

class TestWorkSettingsRouting(SimpleTestCase):
    def test_app_api_route_resolves(self):
        from plane.workload.views import WorkloadSettingsEndpoint

        match = resolve("/api/workspaces/acme/work-settings/")
        self.assertEqual(match.func.view_class, WorkloadSettingsEndpoint)

    def test_public_api_route_resolves(self):
        from plane.workload.api_views import WorkloadSettingsAPIEndpoint

        match = resolve("/api/v1/workspaces/acme/work-settings/")
        self.assertEqual(match.func.view_class, WorkloadSettingsAPIEndpoint)


# ---------------------------------------------------------------------------
# HTTP-layer tests — view handler + @allow_permission decorator, app API.
# Uses DRF APIClient with force_authenticate to exercise the full request
# path: URL dispatch -> @allow_permission -> settings_get/settings_put.
# ---------------------------------------------------------------------------

class TestWorkSettingsHTTP(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, slug):
        return f"/api/workspaces/{slug}/work-settings/"

    def test_get_default_fallback_for_workspace_with_no_row(self):
        """A workspace with no WorkloadSettings row must return the
        constants.py defaults on GET, never 404, and must NOT create a row
        as a side effect of the read."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        resp = self.client.get(self._url(ws.slug))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.data,
            {
                "max_daily_hours": DEFAULT_MAX_DAILY_HOURS,
                "workdays": list(DEFAULT_WORKDAYS),
                "week_start_day": DEFAULT_WEEK_START_DAY,
            },
        )
        self.assertFalse(WorkloadSettings.objects.filter(workspace=ws).exists())

    def test_put_round_trip(self):
        """ADMIN PUT writes a row; a subsequent GET returns exactly what was
        written (round-trip), and workdays come back sorted ascending."""
        ws = _ws()
        admin = _user()
        _wmember(ws, admin, role=20)
        self.client.force_authenticate(user=admin)

        payload = {"max_daily_hours": 32.5, "workdays": [3, 1, 2], "week_start_day": 0}
        put_resp = self.client.put(self._url(ws.slug), payload, format="json")
        self.assertEqual(put_resp.status_code, 200)
        self.assertEqual(put_resp.data["max_daily_hours"], 32.5)
        self.assertEqual(put_resp.data["workdays"], [1, 2, 3])
        self.assertEqual(put_resp.data["week_start_day"], 0)

        get_resp = self.client.get(self._url(ws.slug))
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.data, put_resp.data)
        self.assertEqual(WorkloadSettings.objects.filter(workspace=ws).count(), 1)

    def test_put_is_update_or_create_not_duplicate(self):
        ws = _ws()
        admin = _user()
        _wmember(ws, admin, role=20)
        self.client.force_authenticate(user=admin)

        self.client.put(
            self._url(ws.slug),
            {"max_daily_hours": 8.0, "workdays": [1, 2, 3, 4, 5], "week_start_day": 1},
            format="json",
        )
        self.client.put(
            self._url(ws.slug),
            {"max_daily_hours": 20.0, "workdays": [0, 6], "week_start_day": 0},
            format="json",
        )

        self.assertEqual(WorkloadSettings.objects.filter(workspace=ws).count(), 1)
        obj = WorkloadSettings.objects.get(workspace=ws)
        self.assertEqual(obj.max_daily_hours, 20.0)
        self.assertEqual(obj.workdays, [0, 6])

    def test_put_with_old_max_weekly_hours_key_rejected(self):
        """D2 (plan.md) — no backward-compat alias: a PUT body carrying the
        retired weekly key and no `max_daily_hours` at all is rejected (400),
        not silently accepted with the model default silently applied."""
        ws = _ws()
        admin = _user()
        _wmember(ws, admin, role=20)
        self.client.force_authenticate(user=admin)

        resp = self.client.put(
            self._url(ws.slug),
            {"max_weekly_hours": 8.0, "workdays": [1, 2, 3, 4, 5], "week_start_day": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("max_weekly_hours", resp.data)
        self.assertFalse(WorkloadSettings.objects.filter(workspace=ws).exists())

    def test_put_as_member_is_403(self):
        """PUT is ADMIN-only (plan D-B3 pattern) — a plain MEMBER is rejected
        by @allow_permission before the handler runs."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        resp = self.client.put(
            self._url(ws.slug),
            {"max_daily_hours": 8.0, "workdays": [1, 2, 3, 4, 5], "week_start_day": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(WorkloadSettings.objects.filter(workspace=ws).exists())

    def test_get_as_member_is_allowed(self):
        """GET is ADMIN|MEMBER — non-admins can read (phase-0.md)."""
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        resp = self.client.get(self._url(ws.slug))
        self.assertEqual(resp.status_code, 200)

    def test_403_for_non_member(self):
        ws = _ws()
        outsider = _user()
        self.client.force_authenticate(user=outsider)

        resp = self.client.get(self._url(ws.slug))
        self.assertEqual(resp.status_code, 403)

    def test_put_empty_workdays_is_400(self):
        ws = _ws()
        admin = _user()
        _wmember(ws, admin, role=20)
        self.client.force_authenticate(user=admin)

        resp = self.client.put(
            self._url(ws.slug),
            {"max_daily_hours": 8.0, "workdays": [], "week_start_day": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("workdays", resp.data)
        self.assertFalse(WorkloadSettings.objects.filter(workspace=ws).exists())

    def test_put_week_start_day_7_is_400(self):
        ws = _ws()
        admin = _user()
        _wmember(ws, admin, role=20)
        self.client.force_authenticate(user=admin)

        resp = self.client.put(
            self._url(ws.slug),
            {"max_daily_hours": 8.0, "workdays": [1, 2, 3, 4, 5], "week_start_day": 7},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("week_start_day", resp.data)
        self.assertFalse(WorkloadSettings.objects.filter(workspace=ws).exists())

    def test_put_negative_max_daily_hours_is_400(self):
        ws = _ws()
        admin = _user()
        _wmember(ws, admin, role=20)
        self.client.force_authenticate(user=admin)

        resp = self.client.put(
            self._url(ws.slug),
            {"max_daily_hours": -1, "workdays": [1, 2, 3, 4, 5], "week_start_day": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("max_daily_hours", resp.data)
        self.assertFalse(WorkloadSettings.objects.filter(workspace=ws).exists())


# ---------------------------------------------------------------------------
# HTTP-layer tests — public API (/api/v1/), mirrors the app-API tests above
# for the parts that are surface-specific (auth path, route).
# ---------------------------------------------------------------------------

class TestWorkSettingsPublicAPIHTTP(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, slug):
        return f"/api/v1/workspaces/{slug}/work-settings/"

    def test_get_default_fallback(self):
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        resp = self.client.get(self._url(ws.slug))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.data,
            {
                "max_daily_hours": DEFAULT_MAX_DAILY_HOURS,
                "workdays": list(DEFAULT_WORKDAYS),
                "week_start_day": DEFAULT_WEEK_START_DAY,
            },
        )

    def test_put_round_trip(self):
        ws = _ws()
        admin = _user()
        _wmember(ws, admin, role=20)
        self.client.force_authenticate(user=admin)

        payload = {"max_daily_hours": 25.0, "workdays": [1, 2, 3], "week_start_day": 1}
        put_resp = self.client.put(self._url(ws.slug), payload, format="json")
        self.assertEqual(put_resp.status_code, 200)

        get_resp = self.client.get(self._url(ws.slug))
        self.assertEqual(get_resp.data, put_resp.data)

    def test_put_as_member_is_403(self):
        ws = _ws()
        member = _user()
        _wmember(ws, member, role=15)
        self.client.force_authenticate(user=member)

        resp = self.client.put(
            self._url(ws.slug),
            {"max_daily_hours": 8.0, "workdays": [1, 2, 3, 4, 5], "week_start_day": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
