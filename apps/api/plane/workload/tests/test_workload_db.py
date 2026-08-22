# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# DB integration tests (real Postgres) for owner attribution, the cross-project
# access boundary, state defaults, and reconciliation. Mirrors the ai_ext test
# style (TransactionTestCase + explicit ORM rows, no mocking the unit under test).

import uuid
from datetime import date, datetime, timedelta, timezone

from django.test import TransactionTestCase

# Run Celery tasks inline (no broker in tests). Issue creation enqueues an
# activity task; eager + non-propagating means it runs without a broker and a
# failure inside it never breaks the unit under test.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.service import (
    compute_workload,
    resolve_project_scope,
    _resolve_owners,
)

WIN_FROM = date(2026, 1, 1)
WIN_TO = date(2026, 12, 31)


def _ws(slug=None):
    from plane.db.models import User, Workspace

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


def _wmember(ws, user, role=20):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(
        workspace=ws, member=user, role=role, is_active=True
    )


def _state(ws, proj, group):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws, project=proj, name=f"{group}-{uuid.uuid4().hex[:4]}",
        color="#fff", group=group,
    )


def _issue(ws, proj, state, created_by, start=None, target=None):
    from plane.db.models import Issue

    return Issue.objects.create(
        workspace=ws, project=proj, name=f"i-{uuid.uuid4().hex[:6]}",
        created_by=created_by, state=state, start_date=start, target_date=target,
        sequence_id=1,
    )


def _assign(ws, proj, issue, user, created_at=None):
    from plane.db.models import IssueAssignee

    ia = IssueAssignee.objects.create(
        workspace=ws, project=proj, issue=issue, assignee=user
    )
    if created_at is not None:
        IssueAssignee.objects.filter(pk=ia.pk).update(created_at=created_at)
    return ia


def _estimate(ws, proj, issue, hours):
    from plane.workload.models import WorkloadEstimate

    return WorkloadEstimate.objects.create(
        workspace=ws, project=proj, issue=issue, hours=hours
    )


def _settings(ws, max_daily_hours=8.0, workdays=None, week_start_day=1):
    from plane.workload.models import WorkloadSettings

    kwargs = {"workspace": ws, "max_daily_hours": max_daily_hours, "week_start_day": week_start_day}
    if workdays is not None:
        kwargs["workdays"] = workdays
    return WorkloadSettings.objects.create(**kwargs)


def _t(day):
    return datetime(2026, 1, day, 12, 0, tzinfo=timezone.utc)


class TestOwnerResolution(TransactionTestCase):
    def test_every_active_nonbot_assignee_is_an_owner(self):
        """All assignees are owners, earliest first — an issue is not collapsed
        to one person. Ordering is load-bearing: `compute_workload` hands the
        odd cent of an indivisible split to the earliest assignee."""
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        early = _user()
        late = _user()
        _pmember(ws, proj, early)
        _pmember(ws, proj, late)
        issue = _issue(ws, proj, st, early)
        _assign(ws, proj, issue, late, created_at=_t(2))
        _assign(ws, proj, issue, early, created_at=_t(1))  # earliest

        owners = _resolve_owners([issue.id])
        self.assertEqual([o[0] for o in owners[issue.id]], [early.id, late.id])

    def test_skips_bot_assignee(self):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        bot = _user(is_bot=True)
        human = _user()
        _pmember(ws, proj, bot)
        _pmember(ws, proj, human)
        issue = _issue(ws, proj, st, human)
        _assign(ws, proj, issue, bot, created_at=_t(1))     # earliest but a bot
        _assign(ws, proj, issue, human, created_at=_t(2))

        owners = _resolve_owners([issue.id])
        self.assertEqual([o[0] for o in owners[issue.id]], [human.id])

    def test_skips_inactive_member(self):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        gone = _user()
        active = _user()
        _pmember(ws, proj, gone, is_active=False)   # left the project
        _pmember(ws, proj, active)
        issue = _issue(ws, proj, st, active)
        _assign(ws, proj, issue, gone, created_at=_t(1))
        _assign(ws, proj, issue, active, created_at=_t(2))

        owners = _resolve_owners([issue.id])
        self.assertEqual([o[0] for o in owners[issue.id]], [active.id])

    def test_no_assignee_is_unassigned(self):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        u = _user()
        _pmember(ws, proj, u)
        issue = _issue(ws, proj, st, u)
        owners = _resolve_owners([issue.id])
        self.assertNotIn(issue.id, owners)


class TestAccessBoundary(TransactionTestCase):
    def test_cross_project_request_is_intersected(self):
        """Member of P1 only requesting P2 must get an empty scope (no leak)."""
        ws = _ws()
        p1 = _project(ws)
        p2 = _project(ws)
        user = _user()
        _pmember(ws, p1, user)  # NOT a member of p2

        scope = resolve_project_scope(user, ws.slug, requested_ids=[p2.id])
        self.assertEqual(scope, set())

        scope_default = resolve_project_scope(user, ws.slug, requested_ids=[])
        self.assertEqual(scope_default, {p1.id})

    def test_workspace_admin_sees_all_projects(self):
        ws = _ws()
        p1 = _project(ws)
        p2 = _project(ws)
        admin = _user()
        _wmember(ws, admin, role=20)  # workspace admin, no ProjectMember rows
        scope = resolve_project_scope(admin, ws.slug, requested_ids=[])
        self.assertEqual(scope, {p1.id, p2.id})

    def test_compute_excludes_unauthorized_project_issue(self):
        ws = _ws()
        p1 = _project(ws)
        p2 = _project(ws)
        user = _user()
        _pmember(ws, p1, user)
        other = _user()
        _pmember(ws, p2, other)
        st2 = _state(ws, p2, "started")
        issue2 = _issue(ws, p2, st2, other, start=date(2026, 6, 1), target=date(2026, 6, 1))
        _assign(ws, p2, issue2, other, created_at=_t(1))
        _estimate(ws, p2, issue2, 8.0)

        data = compute_workload(user, ws.slug, "week", WIN_FROM, WIN_TO)
        self.assertEqual(data["rows"], [])
        self.assertEqual(data["meta"]["issues_counted"], 0)

    def test_flag_off_guest_sees_only_own_workload(self):
        """Core parity: a GUEST in a guest_view_all_features=False project sees
        only their own assigned workload, not teammates'."""
        ws = _ws()
        proj = _project(ws)  # guest_view_all_features defaults to False
        st = _state(ws, proj, "started")
        guest = _user()
        other = _user()
        _pmember(ws, proj, guest, role=5)
        _pmember(ws, proj, other, role=15)

        i_self = _issue(ws, proj, st, guest, start=date(2026, 6, 1), target=date(2026, 6, 1))
        _assign(ws, proj, i_self, guest, created_at=_t(1))
        _estimate(ws, proj, i_self, 4.0)
        i_other = _issue(ws, proj, st, other, start=date(2026, 6, 1), target=date(2026, 6, 1))
        _assign(ws, proj, i_other, other, created_at=_t(1))
        _estimate(ws, proj, i_other, 8.0)

        data = compute_workload(guest, ws.slug, "week", WIN_FROM, WIN_TO)
        self.assertEqual({r["assignee_id"] for r in data["rows"]}, {str(guest.id)})
        self.assertEqual(data["meta"]["issues_counted"], 1)

    def test_flag_on_guest_sees_all_workload(self):
        """With guest_view_all_features=True the guest sees the whole team."""
        ws = _ws()
        proj = _project(ws)
        proj.guest_view_all_features = True
        proj.save()
        st = _state(ws, proj, "started")
        guest = _user()
        other = _user()
        _pmember(ws, proj, guest, role=5)
        _pmember(ws, proj, other, role=15)

        i_self = _issue(ws, proj, st, guest, start=date(2026, 6, 1), target=date(2026, 6, 1))
        _assign(ws, proj, i_self, guest, created_at=_t(1))
        _estimate(ws, proj, i_self, 4.0)
        i_other = _issue(ws, proj, st, other, start=date(2026, 6, 1), target=date(2026, 6, 1))
        _assign(ws, proj, i_other, other, created_at=_t(1))
        _estimate(ws, proj, i_other, 8.0)

        data = compute_workload(guest, ws.slug, "week", WIN_FROM, WIN_TO)
        self.assertEqual(
            {r["assignee_id"] for r in data["rows"]},
            {str(guest.id), str(other.id)},
        )
        self.assertEqual(data["meta"]["issues_counted"], 2)


class TestStateDefaults(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        return ws, proj, u

    def test_no_state_filter_includes_completed_and_cancelled(self):
        """An unselected filter must return EVERYTHING.

        This previously asserted the opposite: completed and cancelled were
        excluded whenever the caller passed no `state_group`. That made a
        workspace whose work was finished render an empty matrix while the
        toolbar showed every chip unselected -- the UI said "no filter" while
        the server applied one the user could not see or clear.
        """
        ws, proj, u = self._setup()
        for group in ("started", "completed", "cancelled"):
            st = _state(ws, proj, group)
            issue = _issue(ws, proj, st, u, start=date(2026, 6, 1), target=date(2026, 6, 1))
            _assign(ws, proj, issue, u, created_at=_t(1))
            _estimate(ws, proj, issue, 5.0)

        data = compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO)
        self.assertEqual(data["meta"]["issues_counted"], 3)

    def test_triage_still_excluded_with_no_filter(self):
        """Triage is not a work item yet, so it stays excluded unconditionally --
        that exclusion is a different thing from hiding real, finished work."""
        ws, proj, u = self._setup()
        for group in ("started", "triage"):
            st = _state(ws, proj, group)
            issue = _issue(ws, proj, st, u, start=date(2026, 6, 1), target=date(2026, 6, 1))
            _assign(ws, proj, issue, u, created_at=_t(1))
            _estimate(ws, proj, issue, 5.0)

        data = compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO)
        self.assertEqual(data["meta"]["issues_counted"], 1)

    def test_completed_issue_past_target_is_not_overdue(self):
        """Including completed work must not make it read as late."""
        ws, proj, u = self._setup()
        st = _state(ws, proj, "completed")
        issue = _issue(ws, proj, st, u, start=date(2026, 6, 1), target=date(2026, 6, 1))
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 5.0)

        data = compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO)
        tasks = [t for row in data["rows"] for t in (row.get("tasks") or [])]
        self.assertEqual(len(tasks), 1)
        self.assertFalse(tasks[0]["overdue"])

    def test_state_group_override_includes_completed(self):
        ws, proj, u = self._setup()
        st = _state(ws, proj, "completed")
        issue = _issue(ws, proj, st, u, start=date(2026, 6, 1), target=date(2026, 6, 1))
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 5.0)

        data = compute_workload(
            u, ws.slug, "week", WIN_FROM, WIN_TO, state_groups=["completed"]
        )
        self.assertEqual(data["meta"]["issues_counted"], 1)


class TestCapacityOverload(TransactionTestCase):
    """Phase 3 (D1): capacity is workspace-wide (`WorkloadSettings`), not
    per-member (`WorkloadCapacity`, deleted this phase). Every row now
    carries `over`/`total_over` — even a member with no explicit settings
    row gets the constants.py default applied (previously: empty/no-op)."""

    def test_settings_injected_and_over_flagged(self):
        """Per-period overload still fires; `total_over` no longer does.

        BEHAVIOUR CHANGE (window-complete periods): this test used to assert
        `total_over is True` for 8h logged on ONE day of a FULL-YEAR window.
        That only held because `periods` listed populated buckets only, so
        `total_capacity` priced exactly the one day that had hours (1.0h) —
        i.e. the assertion encoded the very defect that produced a "120h"
        denominator in the UI. Against the whole window the same 8h sits
        against ~261 workdays of capacity and is emphatically not over.

        The overload signal that survives is the one the UI actually needs:
        `over[period]` for the loaded day.
        """
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        monday = date(2026, 6, 15)  # workday -> day cap = max_daily_hours
        issue = _issue(ws, proj, st, u, start=monday, target=monday)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 8.0)
        _settings(ws, max_daily_hours=1.0)  # 1.0h, well under the 8h logged

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        row = next(r for r in data["rows"] if r["assignee_id"] == str(u.id))
        period = monday.isoformat()
        self.assertEqual(row["capacity_buckets"][period], 1.0)
        self.assertTrue(row["over"][period])

        # Window-wide: 8h against a year of 1.0h workdays is not over.
        self.assertFalse(row["total_over"])
        total_capacity = sum(row["capacity_buckets"].values())
        self.assertGreater(total_capacity, 200.0)


    def test_settings_under_load_is_not_over(self):
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        monday = date(2026, 6, 15)
        issue = _issue(ws, proj, st, u, start=monday, target=monday)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 4.0)
        _settings(ws, max_daily_hours=8.0)  # 8.0h, well above the 4h logged

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        row = next(r for r in data["rows"] if r["assignee_id"] == str(u.id))
        period = monday.isoformat()
        self.assertEqual(row["capacity_buckets"][period], 8.0)
        self.assertFalse(row["over"][period])
        self.assertFalse(row["total_over"])

    def test_no_settings_row_falls_back_to_default_and_still_flags(self):
        """No WorkloadSettings row -> constants.py default (8h/day, Mon-Fri)
        applies, and the row STILL carries capacity/over flags (D1) — unlike
        the pre-Phase-3 per-member behaviour, absence no longer means empty."""
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        monday = date(2026, 6, 15)
        issue = _issue(ws, proj, st, u, start=monday, target=monday)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 8.0)  # exactly the default day cap (8.0)

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        row = next(r for r in data["rows"] if r["assignee_id"] == str(u.id))
        period = monday.isoformat()
        self.assertEqual(row["capacity_buckets"][period], 8.0)
        self.assertFalse(row["over"][period])
        self.assertFalse(row["total_over"])

    def test_settings_is_workspace_wide_not_leaked_cross_workspace(self):
        """A settings row in a DIFFERENT workspace must never apply here —
        ws1 (no settings row) must see the constants.py default, not ws2's."""
        ws1 = _ws()
        ws2 = _ws()
        proj = _project(ws1)
        u = _user()
        _pmember(ws1, proj, u)
        st = _state(ws1, proj, "started")
        monday = date(2026, 6, 15)
        issue = _issue(ws1, proj, st, u, start=monday, target=monday)
        _assign(ws1, proj, issue, u, created_at=_t(1))
        _estimate(ws1, proj, issue, 8.0)
        _settings(ws2, max_daily_hours=1.0)  # wrong workspace — must not be picked up

        data = compute_workload(u, ws1.slug, "day", WIN_FROM, WIN_TO)
        row = next(r for r in data["rows"] if r["assignee_id"] == str(u.id))
        period = monday.isoformat()
        # If ws2's 1.0 leaked in, day cap would read 1.0 and this would be "over".
        self.assertEqual(row["capacity_buckets"][period], 8.0)
        self.assertFalse(row["over"][period])
        self.assertFalse(row["total_over"])


class TestWindowCompletePeriods(TransactionTestCase):
    """`periods` is a function of the REQUESTED WINDOW, not of which buckets
    happened to receive hours. This is what gives every visible column a
    capacity figure and a heat cell, and what stops one member's denominator
    from moving when an unrelated member schedules work into a new week."""

    def test_zero_hour_period_still_gets_capacity_and_a_not_over_flag(self):
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        monday = date(2026, 6, 15)
        issue = _issue(ws, proj, st, u, start=monday, target=monday)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 4.0)

        win_from, win_to = date(2026, 6, 15), date(2026, 6, 28)  # two full weeks
        data = compute_workload(u, ws.slug, "week", win_from, win_to)
        row = next(r for r in data["rows"] if r["assignee_id"] == str(u.id))

        # Both weeks are columns, though only the first has hours.
        self.assertEqual(data["periods"], ["2026-06-15", "2026-06-22"])
        self.assertNotIn("2026-06-22", row["buckets"])          # sparse: no hours
        self.assertEqual(row["capacity_buckets"]["2026-06-22"], 40.0)  # but priced
        self.assertFalse(row["over"]["2026-06-22"])             # and explicitly not over

    def test_denominator_does_not_move_when_another_member_schedules_work(self):
        """The reported defect, reduced: u1's capacity denominator must be
        identical whether or not u2 has work in a week u1 never touches."""
        ws = _ws()
        proj = _project(ws)
        u1, u2 = _user(), _user()
        _pmember(ws, proj, u1)
        _pmember(ws, proj, u2)
        st = _state(ws, proj, "started")
        win_from, win_to = date(2026, 6, 15), date(2026, 7, 12)

        first_monday = date(2026, 6, 15)
        i1 = _issue(ws, proj, st, u1, start=first_monday, target=first_monday)
        _assign(ws, proj, i1, u1, created_at=_t(1))
        _estimate(ws, proj, i1, 6.0)

        before = compute_workload(u1, ws.slug, "week", win_from, win_to)
        cap_before = sum(
            next(r for r in before["rows"] if r["assignee_id"] == str(u1.id))[
                "capacity_buckets"
            ].values()
        )

        # u2 now books work in a LATER week that u1 has nothing in.
        later_monday = date(2026, 7, 6)
        i2 = _issue(ws, proj, st, u2, start=later_monday, target=later_monday)
        _assign(ws, proj, i2, u2, created_at=_t(1))
        _estimate(ws, proj, i2, 9.0)

        after = compute_workload(u1, ws.slug, "week", win_from, win_to)
        cap_after = sum(
            next(r for r in after["rows"] if r["assignee_id"] == str(u1.id))[
                "capacity_buckets"
            ].values()
        )

        self.assertEqual(cap_before, cap_after)
        self.assertEqual(before["periods"], after["periods"])

    def test_populated_bucket_outside_the_window_is_kept_not_dropped(self):
        """A week key can precede `date_from`: hours are clipped to the window
        but keyed off the un-clipped day. The union must keep that column, or
        those hours would render nowhere."""
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")

        # Wed Jun 17; the window opens on that day, but its Monday-start week
        # bucket is Jun 15, two days earlier.
        wednesday = date(2026, 6, 17)
        issue = _issue(ws, proj, st, u, start=wednesday, target=wednesday)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 5.0)

        data = compute_workload(u, ws.slug, "week", wednesday, date(2026, 6, 28))
        row = next(r for r in data["rows"] if r["assignee_id"] == str(u.id))
        self.assertIn("2026-06-15", data["periods"])
        self.assertEqual(row["buckets"]["2026-06-15"], 5.0)
        self.assertIn("2026-06-15", row["capacity_buckets"])


class TestReconciliation(TransactionTestCase):
    def test_totals_reconcile_within_tolerance(self):
        ws = _ws()
        proj = _project(ws)
        u = _user()
        _pmember(ws, proj, u)
        st = _state(ws, proj, "started")
        # Awkward divisions that stress the cents distribution.
        specs = [(10.0, 3), (7.0, 7), (100.0, 13), (0.05, 2)]
        total_hours = 0.0
        for hours, span in specs:
            start = date(2026, 6, 1)
            target = start + timedelta(days=span - 1)
            issue = _issue(ws, proj, st, u, start=start, target=target)
            _assign(ws, proj, issue, u, created_at=_t(1))
            _estimate(ws, proj, issue, hours)
            total_hours += hours

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        bucket_sum = sum(
            v for row in data["rows"] for v in row["buckets"].values()
        )
        unsched = sum(x["hours"] for x in data["unscheduled"])
        self.assertAlmostEqual(bucket_sum + unsched, total_hours, places=2)


class TestSharedAssigneeSplit(TransactionTestCase):
    """A work item may carry several assignees (ClickUp parity). Its hours are
    split EVENLY across them, and the shares must re-sum to the estimate — the
    matrix must neither double-count a shared task nor credit it to one person.
    """

    def _shared_issue(self, n_assignees, hours, start=None, target=None):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        users = [_user() for _ in range(n_assignees)]
        for u in users:
            _pmember(ws, proj, u)
        issue = _issue(ws, proj, st, users[0], start=start, target=target)
        for day, u in enumerate(users, start=1):
            _assign(ws, proj, issue, u, created_at=_t(day))
        _estimate(ws, proj, issue, hours)
        return ws, proj, users, issue

    def _rows_by_user(self, data):
        return {r["assignee_id"]: r for r in data["rows"]}

    def test_two_assignees_each_carry_half(self):
        d = date(2026, 6, 1)  # a Monday — one workday, one bucket
        ws, _, users, _ = self._shared_issue(2, 8.0, start=d, target=d)

        data = compute_workload(users[0], ws.slug, "day", WIN_FROM, WIN_TO)
        rows = self._rows_by_user(data)

        self.assertEqual(len(rows), 2)
        for u in users:
            self.assertEqual(rows[str(u.id)]["total"], 4.0)
            self.assertEqual(rows[str(u.id)]["buckets"]["2026-06-01"], 4.0)

    def test_shared_hours_are_not_double_counted(self):
        """The whole matrix must still sum to the issue's estimate, once."""
        d = date(2026, 6, 1)
        ws, _, users, _ = self._shared_issue(4, 10.0, start=d, target=d)

        data = compute_workload(users[0], ws.slug, "day", WIN_FROM, WIN_TO)
        grand_total = sum(r["total"] for r in data["rows"])
        self.assertEqual(grand_total, 10.0)
        self.assertEqual(len(data["rows"]), 4)

    def test_indivisible_split_loses_no_cent(self):
        """10h / 3 is not representable in cents. The shares must still re-sum
        to exactly 10h, with the odd cent going to the earliest assignee."""
        d = date(2026, 6, 1)
        ws, _, users, _ = self._shared_issue(3, 10.0, start=d, target=d)

        data = compute_workload(users[0], ws.slug, "day", WIN_FROM, WIN_TO)
        rows = self._rows_by_user(data)
        totals = [rows[str(u.id)]["total"] for u in users]

        self.assertEqual(sum(totals), 10.0)
        self.assertEqual(totals, [3.34, 3.33, 3.33])  # earliest assignee absorbs it

    def test_split_holds_across_a_multi_day_span(self):
        """Each PERIOD is split, not just the row total, so a shared task that
        spans several days is even in every column it touches."""
        start = date(2026, 6, 1)   # Mon
        target = date(2026, 6, 5)  # Fri — 5 workdays
        ws, _, users, _ = self._shared_issue(2, 10.0, start=start, target=target)

        data = compute_workload(users[0], ws.slug, "day", WIN_FROM, WIN_TO)
        rows = self._rows_by_user(data)
        for u in users:
            b = rows[str(u.id)]["buckets"]
            self.assertEqual(rows[str(u.id)]["total"], 5.0)
            # 10h over 5 workdays = 2h/day, halved = 1h/day each
            for day in range(1, 6):
                self.assertEqual(b[f"2026-06-0{day}"], 1.0)

    def test_unscheduled_hours_split_too(self):
        """An issue with no target lands in Unscheduled — also per-owner."""
        ws, _, users, _ = self._shared_issue(2, 9.0)  # no start, no target

        data = compute_workload(users[0], ws.slug, "day", WIN_FROM, WIN_TO)
        unsched = {x["assignee_id"]: x["hours"] for x in data["unscheduled"]}
        self.assertEqual(sorted(unsched.values()), [4.5, 4.5])
        self.assertEqual(sum(unsched.values()), 9.0)

    def test_assignee_filter_returns_the_share_not_the_whole_estimate(self):
        """Filtering to one person must not hand them their co-owners' hours:
        the split is computed over ALL owners, then filtered."""
        d = date(2026, 6, 1)
        ws, _, users, _ = self._shared_issue(2, 8.0, start=d, target=d)

        data = compute_workload(
            users[0], ws.slug, "day", WIN_FROM, WIN_TO, assignee_ids=[users[1].id]
        )
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["assignee_id"], str(users[1].id))
        self.assertEqual(data["rows"][0]["total"], 4.0)

    def test_task_row_reports_share_and_undivided_total(self):
        d = date(2026, 6, 1)
        ws, _, users, _ = self._shared_issue(2, 8.0, start=d, target=d)

        data = compute_workload(users[0], ws.slug, "day", WIN_FROM, WIN_TO)
        rows = self._rows_by_user(data)
        for u in users:
            task = rows[str(u.id)]["tasks"][0]
            self.assertEqual(task["hours"], 4.0)          # this person's share
            self.assertEqual(task["total_hours"], 8.0)    # the undivided estimate
            self.assertEqual(task["assignee_count"], 2)

    def test_sole_assignee_is_unchanged(self):
        """The single-owner path must behave exactly as before the split."""
        d = date(2026, 6, 1)
        ws, _, users, _ = self._shared_issue(1, 8.0, start=d, target=d)

        data = compute_workload(users[0], ws.slug, "day", WIN_FROM, WIN_TO)
        row = data["rows"][0]
        self.assertEqual(row["total"], 8.0)
        self.assertEqual(row["tasks"][0]["hours"], 8.0)
        self.assertEqual(row["tasks"][0]["total_hours"], 8.0)
        self.assertEqual(row["tasks"][0]["assignee_count"], 1)


class TestSharedSplitReachesTheHttpResponse(TransactionTestCase):
    """The workload VIEW renders `row.buckets` / `row.capacity_buckets` /
    `row.over` straight from this endpoint's JSON — it never re-derives hours
    from `tasks[]`. `WorkspaceWorkloadEndpoint` returns `compute_workload`'s
    dict verbatim (no serializer), but "verbatim" is an inference about the
    code, not a fact about the response. This test asserts the fact: the split
    a shared work item gets in the service is what the HTTP layer actually
    hands the browser.
    """

    def test_endpoint_returns_the_split_not_the_whole_estimate(self):
        from django.test import Client

        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        alice = _user()
        bob = _user()
        for u in (alice, bob):
            _pmember(ws, proj, u)
            _wmember(ws, u, role=20)
        d = date(2026, 6, 1)  # Monday — a single workday, a single bucket
        issue = _issue(ws, proj, st, alice, start=d, target=d)
        _assign(ws, proj, issue, alice, created_at=_t(1))
        _assign(ws, proj, issue, bob, created_at=_t(2))
        _estimate(ws, proj, issue, 8.0)

        client = Client()
        client.force_login(alice)
        resp = client.get(
            f"/api/workspaces/{ws.slug}/workload/",
            {"granularity": "day", "date_from": "2026-06-01", "date_to": "2026-06-30"},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()

        rows = {r["assignee_id"]: r for r in body["rows"]}
        self.assertEqual(sorted(rows), sorted([str(alice.id), str(bob.id)]))
        for u in (alice, bob):
            # What the heat cell reads, and what the sidebar total sums.
            self.assertEqual(rows[str(u.id)]["buckets"]["2026-06-01"], 4.0)
            self.assertEqual(rows[str(u.id)]["total"], 4.0)
            # What the timeline bar prints, and what its tooltip explains.
            task = rows[str(u.id)]["tasks"][0]
            self.assertEqual(task["hours"], 4.0)
            self.assertEqual(task["total_hours"], 8.0)
            self.assertEqual(task["assignee_count"], 2)

        # The work is counted ONCE across the whole matrix, not once per person.
        self.assertEqual(sum(r["total"] for r in body["rows"]), 8.0)
