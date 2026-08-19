# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# `weekly_buckets` / `weekly_capacity` — the always-weekly aggregation behind
# the timeline's `NNh/40h` badge and the over-capacity signal.
#
# The property these tests exist to pin: the weekly figures are INDEPENDENT of
# `granularity`. The badge is defined per week; the columns are bucketed by
# whatever zoom level the user picked. Deriving the badge from `buckets` would
# make it unreadable at `month` (a week is not recoverable from a month bucket)
# and would re-derive the week-start convention at `day` — which is exactly the
# duplication `period_key` exists to prevent.
#
# Fixture style mirrors test_workload_db.py / test_task_rows.py deliberately,
# so all three stay in sync.

import uuid
from datetime import date, datetime, timezone

from django.test import TransactionTestCase

# Run Celery tasks inline (no broker in tests) — see test_task_rows.py.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.service import compute_workload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _user(email=None):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    return User.objects.create_user(
        username=f"user_{uid}", email=email or f"u-{uid}@test.invalid", password="x"
    )


def _ws(slug=None, timezone_name="UTC"):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(
        name=slug, slug=slug, logo="", owner=_user(), timezone=timezone_name
    )


def _project(ws, identifier=None):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=identifier or uuid.uuid4().hex[:5].upper(),
    )


def _pmember(ws, proj, user, role=15):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(
        workspace=ws, project=proj, member=user, role=role, is_active=True
    )


def _state(ws, proj, group):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws, project=proj, name=f"{group}-{uuid.uuid4().hex[:4]}",
        color="#fff", group=group,
    )


def _issue(ws, proj, state, created_by, start=None, target=None, name=None):
    from plane.db.models import Issue

    return Issue.objects.create(
        workspace=ws, project=proj, name=name or f"i-{uuid.uuid4().hex[:6]}",
        created_by=created_by, state=state, start_date=start, target_date=target,
    )


def _assign(ws, proj, issue, user):
    from plane.db.models import IssueAssignee

    ia = IssueAssignee.objects.create(
        workspace=ws, project=proj, issue=issue, assignee=user
    )
    IssueAssignee.objects.filter(pk=ia.pk).update(
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    )
    return ia


def _estimate(ws, proj, issue, hours):
    from plane.workload.models import WorkloadEstimate

    return WorkloadEstimate.objects.create(
        workspace=ws, project=proj, issue=issue, hours=hours
    )


def _settings(ws, max_weekly_hours=None, workdays=None, week_start_day=None):
    from plane.workload.models import WorkloadSettings

    kwargs = {}
    if max_weekly_hours is not None:
        kwargs["max_weekly_hours"] = max_weekly_hours
    if workdays is not None:
        kwargs["workdays"] = workdays
    if week_start_day is not None:
        kwargs["week_start_day"] = week_start_day
    return WorkloadSettings.objects.create(workspace=ws, **kwargs)


def _rowfor(data, user):
    return next(r for r in data["rows"] if r["assignee_id"] == str(user.id))


WIN_FROM = date(2026, 6, 1)
WIN_TO = date(2026, 7, 31)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWeeklyBucketsAreGranularityIndependent(TransactionTestCase):
    def test_identical_at_day_week_and_month(self):
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")

        # Mon Jun 15 -> Wed Jun 17, 9h spread over three workdays.
        issue = _issue(ws, proj, st, u, start=date(2026, 6, 15), target=date(2026, 6, 17))
        _assign(ws, proj, issue, u)
        _estimate(ws, proj, issue, 9.0)

        results = {
            gran: _rowfor(compute_workload(u, ws.slug, gran, WIN_FROM, WIN_TO), u)
            for gran in ("day", "week", "month")
        }

        weekly = [r["weekly_buckets"] for r in results.values()]
        self.assertEqual(weekly[0], weekly[1])
        self.assertEqual(weekly[1], weekly[2])
        self.assertEqual(weekly[0], {"2026-06-15": 9.0})

        for gran, row in results.items():
            self.assertEqual(row["weekly_capacity"], 40.0, gran)

    def test_columns_still_differ_by_granularity(self):
        """Guards the inverse: `buckets` must NOT have been flattened to weeks
        as a side effect — the two aggregations are independent, not merged."""
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        issue = _issue(ws, proj, st, u, start=date(2026, 6, 15), target=date(2026, 6, 17))
        _assign(ws, proj, issue, u)
        _estimate(ws, proj, issue, 9.0)

        day = _rowfor(compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO), u)
        month = _rowfor(compute_workload(u, ws.slug, "month", WIN_FROM, WIN_TO), u)

        self.assertEqual(
            day["buckets"], {"2026-06-15": 3.0, "2026-06-16": 3.0, "2026-06-17": 3.0}
        )
        self.assertEqual(month["buckets"], {"2026-06": 9.0})


class TestWeeklyBucketsSemantics(TransactionTestCase):
    def test_weekend_spanning_task_lands_in_one_week(self):
        """Fri Jun 19 -> Mon Jun 22 crosses a weekend AND a week boundary.
        Hours fall only on workdays (D4), so Fri and Mon each take half — and
        those two days belong to DIFFERENT weeks, which the weekly aggregation
        must reflect rather than collapsing to the start week."""
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        issue = _issue(ws, proj, st, u, start=date(2026, 6, 19), target=date(2026, 6, 22))
        _assign(ws, proj, issue, u)
        _estimate(ws, proj, issue, 8.0)

        row = _rowfor(compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO), u)
        self.assertEqual(row["weekly_buckets"], {"2026-06-15": 4.0, "2026-06-22": 4.0})

    def test_week_start_day_shifts_the_weekly_key(self):
        """A Sunday-start workspace buckets the same Monday into the week that
        began the previous day — the key is the week's first DATE, not an ISO
        week number, so it must move with the setting."""
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        monday = date(2026, 6, 15)
        issue = _issue(ws, proj, st, u, start=monday, target=monday)
        _assign(ws, proj, issue, u)
        _estimate(ws, proj, issue, 6.0)
        _settings(ws, week_start_day=0)  # Sunday

        row = _rowfor(compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO), u)
        self.assertEqual(row["weekly_buckets"], {"2026-06-14": 6.0})

    def test_weekly_capacity_tracks_the_workspace_setting(self):
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        monday = date(2026, 6, 15)
        issue = _issue(ws, proj, st, u, start=monday, target=monday)
        _assign(ws, proj, issue, u)
        _estimate(ws, proj, issue, 50.0)
        _settings(ws, max_weekly_hours=37.5)

        row = _rowfor(compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO), u)
        self.assertEqual(row["weekly_capacity"], 37.5)
        self.assertGreater(row["weekly_buckets"]["2026-06-15"], row["weekly_capacity"])

    def test_unscheduled_task_contributes_no_weekly_hours(self):
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        issue = _issue(ws, proj, st, u, start=None, target=None)
        _assign(ws, proj, issue, u)
        _estimate(ws, proj, issue, 12.0)

        row = _rowfor(compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO), u)
        self.assertEqual(row["weekly_buckets"], {})

    def test_weekly_buckets_are_clipped_to_the_window(self):
        """Hours outside [date_from, date_to] never appear, at any granularity —
        the weekly pass uses the same window as the primary one."""
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        # Two workdays: one inside the window, one after it.
        issue = _issue(ws, proj, st, u, start=date(2026, 7, 30), target=date(2026, 8, 3))
        _assign(ws, proj, issue, u)
        _estimate(ws, proj, issue, 9.0)  # Thu 30, Fri 31, Mon Aug 3 -> 3h each

        row = _rowfor(compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO), u)
        self.assertEqual(row["weekly_buckets"], {"2026-07-27": 6.0})
