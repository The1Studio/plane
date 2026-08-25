# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Unestimated work items on the timeline. DB integration tests (real Postgres)
# for `_unestimated_queryset` and the second assembly loop in
# `compute_workload`. Fixture style mirrors test_task_rows.py deliberately so
# the two files stay in sync.
#
# The invariant most of this file exists to defend: an unestimated item adds a
# TASK ROW and nothing else. Every capacity figure in the response must be
# byte-identical to what it would be if the item were not there — see
# test_unestimated_contributes_no_hours, which asserts that by diffing two
# whole responses rather than by spot-checking fields.

import uuid
from datetime import date, datetime, timedelta, timezone

from django.test import TransactionTestCase

try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.service import (
    ROW_GUARD,
    WORKLOAD_MAX_TASKS_PER_ASSIGNEE,
    WorkloadTooLarge,
    compute_workload,
)

WIN_FROM = date(2026, 1, 1)
WIN_TO = date(2026, 12, 31)
MONDAY = date(2026, 6, 15)


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_task_rows.py)
# ---------------------------------------------------------------------------


def _user(email=None, is_bot=False, display_name=None):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    user = User.objects.create_user(
        username=f"user_{uid}",
        email=email or f"u-{uid}@test.invalid",
        password="x",
        is_bot=is_bot,
    )
    if display_name is not None:
        User.objects.filter(pk=user.pk).update(display_name=display_name)
        user.refresh_from_db()
    return user


def _ws(slug=None, owner=None, timezone_name="UTC"):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(
        name=slug, slug=slug, logo="", owner=owner or _user(), timezone=timezone_name
    )


def _project(ws, identifier=None, guest_view_all_features=True):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=identifier or uuid.uuid4().hex[:5].upper(),
        guest_view_all_features=guest_view_all_features,
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


def _state(ws, proj, group, name=None, color="#fff"):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws,
        project=proj,
        name=name if name is not None else f"{group}-{uuid.uuid4().hex[:4]}",
        color=color,
        group=group,
    )


def _issue(ws, proj, state, created_by, start=None, target=None, name=None, parent=None):
    from plane.db.models import Issue

    return Issue.objects.create(
        workspace=ws,
        project=proj,
        name=name or f"i-{uuid.uuid4().hex[:6]}",
        created_by=created_by,
        state=state,
        start_date=start,
        target_date=target,
        parent=parent,
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


def _rowfor(data, user):
    return next(
        (r for r in data["rows"] if r["assignee_id"] == str(user.id)),
        None,
    )


def _tasks(data, user):
    row = _rowfor(data, user)
    return row["tasks"] if row else []


def _fixture(guest_view_all_features=True):
    """One workspace, one project, one active member, one 'started' state."""
    owner = _user()
    ws = _ws(owner=owner)
    proj = _project(ws, identifier="PLANE", guest_view_all_features=guest_view_all_features)
    st = _state(ws, proj, "started", name="In Review", color="#8b5cf6")
    user = _user(display_name="Uma Unestimated")
    _wmember(ws, user)
    _pmember(ws, proj, user)
    return ws, proj, st, user


# ---------------------------------------------------------------------------
# The two ways an item can be unestimated
# ---------------------------------------------------------------------------


class TestUnestimatedTaskRows(TransactionTestCase):
    def test_no_estimate_row_appears_as_unestimated_task(self):
        ws, proj, st, user = _fixture()
        issue = _issue(
            ws, proj, st, user, start=MONDAY, target=MONDAY + timedelta(days=4),
            name="Needs an estimate",
        )
        _assign(ws, proj, issue, user, created_at=_t(1))

        data = compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
        tasks = _tasks(data, user)

        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertTrue(task["unestimated"])
        self.assertEqual(task["hours"], 0.0)
        self.assertEqual(task["total_hours"], 0.0)
        self.assertEqual(task["assignee_count"], 1)
        # The dates are what the client draws the dashed bar's SPAN from — an
        # unestimated item is not an undated one.
        self.assertEqual(task["start_date"], "2026-06-15")
        self.assertEqual(task["target_date"], "2026-06-19")
        self.assertEqual(task["identifier"], f"PLANE-{issue.sequence_id}")
        self.assertEqual(task["name"], "Needs an estimate")
        # The state fields the bar's border colour comes from ride along
        # exactly as they do on an estimated row.
        self.assertEqual(task["state_name"], "In Review")
        self.assertEqual(task["state_color"], "#8b5cf6")
        self.assertEqual(data["meta"]["issues_unestimated"], 1)

    def test_zero_hour_estimate_appears_as_unestimated(self):
        """A stored `hours = 0` row is not an estimate of zero work — it is the
        other way an item can be unestimated, and `_base_queryset` has always
        filtered it out. It must ALSO still be counted by the pre-existing
        `zero_estimate_count`, which measures something narrower."""
        ws, proj, st, user = _fixture()
        issue = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, issue, user, created_at=_t(1))
        _estimate(ws, proj, issue, 0.0)

        data = compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
        tasks = _tasks(data, user)

        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0]["unestimated"])
        self.assertEqual(data["meta"]["issues_unestimated"], 1)
        # issues_unestimated is a SUPERSET of zero_estimate_count; both see
        # this row.
        self.assertEqual(data["meta"]["zero_estimate_count"], 1)

    def test_estimated_rows_carry_unestimated_false(self):
        """Absent is not false. A missing key reads as falsy and would work by
        accident until a consumer used `in` or a strict schema."""
        ws, proj, st, user = _fixture()
        issue = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, issue, user, created_at=_t(1))
        _estimate(ws, proj, issue, 4.0)

        tasks = _tasks(compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user)
        self.assertEqual(len(tasks), 1)
        self.assertIn("unestimated", tasks[0])
        self.assertIs(tasks[0]["unestimated"], False)
        self.assertEqual(_rowfor(
            compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user
        )["total"], 4.0)

    def test_undated_unestimated_has_null_target(self):
        """`!target_date` is the client's placeholder predicate — an undated
        unestimated item must reach it, or it is invisible on the board."""
        ws, proj, st, user = _fixture()
        issue = _issue(ws, proj, st, user, start=None, target=None)
        _assign(ws, proj, issue, user, created_at=_t(1))

        tasks = _tasks(compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user)
        self.assertEqual(len(tasks), 1)
        self.assertIsNone(tasks[0]["target_date"])
        self.assertIsNone(tasks[0]["start_date"])
        self.assertTrue(tasks[0]["unestimated"])

    def test_out_of_window_unestimated_still_appears(self):
        """The estimated path drops an item whose span misses the window
        because it contributed no bucket. An unestimated item never
        contributes one, so that test would drop EVERY one of them."""
        ws, proj, st, user = _fixture()
        far = date(2030, 3, 3)
        issue = _issue(ws, proj, st, user, start=far, target=far)
        _assign(ws, proj, issue, user, created_at=_t(1))

        tasks = _tasks(compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["target_date"], "2030-03-03")

    def test_overdue_flag_follows_the_same_rule(self):
        ws, proj, st, user = _fixture()
        past = date(2020, 1, 6)
        overdue_issue = _issue(ws, proj, st, user, start=past, target=past)
        _assign(ws, proj, overdue_issue, user, created_at=_t(1))
        undated = _issue(ws, proj, st, user, start=None, target=None)
        _assign(ws, proj, undated, user, created_at=_t(2))

        tasks = {
            t["id"]: t
            for t in _tasks(compute_workload(user, ws.slug, "day", date(2020, 1, 1), WIN_TO), user)
        }
        self.assertTrue(tasks[str(overdue_issue.id)]["overdue"])
        # No target -> never overdue, estimated or not.
        self.assertFalse(tasks[str(undated.id)]["overdue"])


# ---------------------------------------------------------------------------
# The load-bearing invariant: zero effect on every capacity figure
# ---------------------------------------------------------------------------


class TestUnestimatedAddsNoHours(TransactionTestCase):
    def test_unestimated_contributes_no_hours(self):
        """Diff two WHOLE responses rather than spot-checking fields: a future
        capacity field added to the row would otherwise escape this test."""
        ws, proj, st, user = _fixture()
        estimated = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, estimated, user, created_at=_t(1))
        _estimate(ws, proj, estimated, 6.0)

        before = compute_workload(user, ws.slug, "week", WIN_FROM, WIN_TO)

        noise = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY + timedelta(days=10))
        _assign(ws, proj, noise, user, created_at=_t(2))

        after = compute_workload(user, ws.slug, "week", WIN_FROM, WIN_TO)

        row_before = _rowfor(before, user)
        row_after = _rowfor(after, user)
        for field in ("buckets", "month_buckets", "capacity_buckets", "over", "total", "total_over"):
            self.assertEqual(
                row_before[field],
                row_after[field],
                f"an unestimated item moved `{field}` — it must add a task row and nothing else",
            )
        self.assertEqual(before["unscheduled"], after["unscheduled"])
        self.assertEqual(before["periods"], after["periods"])
        # meta.issues_counted describes HOURS, so it must not move either.
        self.assertEqual(before["meta"]["issues_counted"], after["meta"]["issues_counted"])
        self.assertEqual(before["meta"]["issues_unscheduled"], after["meta"]["issues_unscheduled"])
        # The one thing that DID change.
        self.assertEqual(before["meta"]["issues_unestimated"], 0)
        self.assertEqual(after["meta"]["issues_unestimated"], 1)
        self.assertEqual(len(row_after["tasks"]), 2)

    def test_undated_unestimated_is_not_in_the_unscheduled_bucket(self):
        """`unscheduled[]` carries HOURS routed away from the capacity cells.
        An unestimated item has none, so it belongs in neither."""
        ws, proj, st, user = _fixture()
        issue = _issue(ws, proj, st, user, start=None, target=None)
        _assign(ws, proj, issue, user, created_at=_t(1))

        data = compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
        self.assertEqual(data["unscheduled"], [])
        self.assertEqual(data["meta"]["issues_unscheduled"], 0)
        self.assertEqual(data["meta"]["issues_unestimated"], 1)


# ---------------------------------------------------------------------------
# Scope: which items are eligible at all
# ---------------------------------------------------------------------------


class TestUnestimatedScope(TransactionTestCase):
    def test_parent_with_countable_children_is_not_unestimated(self):
        """Leaf-only, the same rule the estimated path applies. A parent
        rendering as an unestimated bar would contradict the rollup its own
        sidebar shows."""
        ws, proj, st, user = _fixture()
        parent = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY, name="Parent")
        _assign(ws, proj, parent, user, created_at=_t(1))
        child = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY, name="Child", parent=parent)
        _assign(ws, proj, child, user, created_at=_t(2))
        _estimate(ws, proj, child, 5.0)

        tasks = _tasks(compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user)
        ids = {t["id"] for t in tasks}
        self.assertNotIn(str(parent.id), ids, "a parent must never appear as unestimated")
        self.assertIn(str(child.id), ids)
        self.assertEqual(_rowfor(
            compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user
        )["total"], 5.0)

    def test_archived_draft_and_cancelled_are_excluded(self):
        from plane.db.models import Issue
        from django.utils import timezone as dj_tz

        ws, proj, st, user = _fixture()
        cancelled_state = _state(ws, proj, "cancelled")

        archived = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, archived, user, created_at=_t(1))
        Issue.objects.filter(pk=archived.pk).update(archived_at=dj_tz.now())

        draft = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, draft, user, created_at=_t(2))
        Issue.objects.filter(pk=draft.pk).update(is_draft=True)

        cancelled = _issue(ws, proj, cancelled_state, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, cancelled, user, created_at=_t(3))

        data = compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
        self.assertEqual(_tasks(data, user), [])
        self.assertEqual(data["meta"]["issues_unestimated"], 0)

    def test_state_group_filter_applies(self):
        ws, proj, st, user = _fixture()
        backlog = _state(ws, proj, "backlog")

        started_issue = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, started_issue, user, created_at=_t(1))
        backlog_issue = _issue(ws, proj, backlog, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, backlog_issue, user, created_at=_t(2))

        data = compute_workload(
            user, ws.slug, "day", WIN_FROM, WIN_TO, state_groups=["started"]
        )
        ids = {t["id"] for t in _tasks(data, user)}
        self.assertEqual(ids, {str(started_issue.id)})

        # No filter selected means EVERY group, never a hidden exclusion.
        unfiltered = compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
        self.assertEqual(len(_tasks(unfiltered, user)), 2)

    def test_flag_off_guest_sees_only_their_own_unestimated_items(self):
        """Exercises the `issue_field="id"` path through `_scope_filter` — the
        Issue queryset keys the guest's own-issue narrowing on `id`, not the
        estimate table's `issue_id`."""
        owner = _user()
        ws = _ws(owner=owner)
        proj = _project(ws, identifier="PLANE", guest_view_all_features=False)
        st = _state(ws, proj, "started")
        guest = _user(display_name="Guest Gus")
        _wmember(ws, guest, role=5)
        _pmember(ws, proj, guest, role=5)
        colleague = _user(display_name="Colleague Cleo")
        _wmember(ws, colleague)
        _pmember(ws, proj, colleague)

        mine = _issue(ws, proj, st, guest, start=MONDAY, target=MONDAY)
        _assign(ws, proj, mine, guest, created_at=_t(1))
        theirs = _issue(ws, proj, st, colleague, start=MONDAY, target=MONDAY)
        _assign(ws, proj, theirs, colleague, created_at=_t(2))

        data = compute_workload(guest, ws.slug, "day", WIN_FROM, WIN_TO)
        all_ids = {t["id"] for row in data["rows"] for t in row["tasks"]}
        self.assertEqual(all_ids, {str(mine.id)})

    def test_unassigned_row_exists_for_unestimated_only_work(self):
        """`tasks_by_owner` is the ONLY map an unestimated item writes to, so
        without it in the `owner_ids` union the Unassigned row disappears:
        `scope_members` contributes member ids and never `None`."""
        ws, proj, st, user = _fixture()
        orphan = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY, name="Nobody's")

        data = compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
        unassigned = next(
            (r for r in data["rows"] if r["assignee_id"] is None), None
        )
        self.assertIsNotNone(unassigned, "the Unassigned row must survive")
        self.assertEqual([t["id"] for t in unassigned["tasks"]], [str(orphan.id)])

    def test_meta_counts_issues_not_owners(self):
        ws, proj, st, user = _fixture()
        second = _user(display_name="Second Sam")
        _wmember(ws, second)
        _pmember(ws, proj, second)
        shared = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, shared, user, created_at=_t(1))
        _assign(ws, proj, shared, second, created_at=_t(2))

        data = compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
        self.assertEqual(data["meta"]["issues_unestimated"], 1)
        # ...but BOTH owners get the task row, and each reports the real
        # assignee count.
        self.assertEqual(len(_tasks(data, user)), 1)
        self.assertEqual(len(_tasks(data, second)), 1)
        self.assertEqual(_tasks(data, user)[0]["assignee_count"], 2)


# ---------------------------------------------------------------------------
# Ordering and the shared cap
# ---------------------------------------------------------------------------


class TestSortAndCap(TransactionTestCase):
    def test_sorted_first_and_shares_cap(self):
        """Unestimated leads `tasks`, and the 200-cap is SHARED — which means a
        big unestimated backlog can now truncate estimated work that used to
        fit. That is the trade `_task_sort_key` documents; this pins it so it
        stays visible in the suite rather than being found on a busy swimlane.
        """
        ws, proj, st, user = _fixture()

        # 3 estimated, all dated EARLIER than the unestimated ones, so a purely
        # date-based sort would put them first. Only the unestimated term can
        # produce the asserted order.
        for i in range(3):
            issue = _issue(ws, proj, st, user, start=date(2026, 2, 1), target=date(2026, 2, 2))
            _assign(ws, proj, issue, user, created_at=_t(1))
            _estimate(ws, proj, issue, 1.0)
        for i in range(2):
            issue = _issue(ws, proj, st, user, start=date(2026, 9, 1), target=date(2026, 9, 2))
            _assign(ws, proj, issue, user, created_at=_t(1))

        tasks = _tasks(compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user)
        self.assertEqual(len(tasks), 5)
        flags = [t["unestimated"] for t in tasks]
        self.assertEqual(
            flags,
            [True, True, False, False, False],
            "unestimated rows must lead the array despite sorting later by date",
        )

    def test_cap_is_shared_not_per_group(self):
        """One budget of WORKLOAD_MAX_TASKS_PER_ASSIGNEE across both kinds."""
        ws, proj, st, user = _fixture()
        total = WORKLOAD_MAX_TASKS_PER_ASSIGNEE + 5
        for _ in range(total):
            issue = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
            _assign(ws, proj, issue, user, created_at=_t(1))

        row = _rowfor(compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO), user)
        self.assertEqual(len(row["tasks"]), WORKLOAD_MAX_TASKS_PER_ASSIGNEE)
        self.assertTrue(row["tasks_truncated"])


class TestRowGuard(TransactionTestCase):
    def test_row_guard_counts_both_querysets(self):
        """ONE budget across both queries, not one ceiling each. Patched low
        rather than creating 50k rows — the arithmetic is what is under test."""
        from unittest.mock import patch

        ws, proj, st, user = _fixture()
        estimated = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, estimated, user, created_at=_t(1))
        _estimate(ws, proj, estimated, 2.0)
        unestimated = _issue(ws, proj, st, user, start=MONDAY, target=MONDAY)
        _assign(ws, proj, unestimated, user, created_at=_t(2))

        # 1 estimated + 1 unestimated = 2. A guard of 1 must trip only because
        # the two are summed; either queryset alone stays under it.
        with patch("plane.workload.service.ROW_GUARD", 1):
            with self.assertRaises(WorkloadTooLarge):
                compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)

        with patch("plane.workload.service.ROW_GUARD", 2):
            compute_workload(user, ws.slug, "day", WIN_FROM, WIN_TO)
