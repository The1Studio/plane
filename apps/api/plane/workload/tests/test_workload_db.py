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


def _t(day):
    return datetime(2026, 1, day, 12, 0, tzinfo=timezone.utc)


class TestOwnerResolution(TransactionTestCase):
    def test_earliest_active_nonbot_is_owner(self):
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
        self.assertEqual(owners[issue.id][0], early.id)

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
        self.assertEqual(owners[issue.id][0], human.id)

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
        self.assertEqual(owners[issue.id][0], active.id)

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

    def test_cancelled_and_completed_excluded_by_default(self):
        ws, proj, u = self._setup()
        for group in ("started", "completed", "cancelled"):
            st = _state(ws, proj, group)
            issue = _issue(ws, proj, st, u, start=date(2026, 6, 1), target=date(2026, 6, 1))
            _assign(ws, proj, issue, u, created_at=_t(1))
            _estimate(ws, proj, issue, 5.0)

        data = compute_workload(u, ws.slug, "week", WIN_FROM, WIN_TO)
        self.assertEqual(data["meta"]["issues_counted"], 1)  # only 'started'

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
