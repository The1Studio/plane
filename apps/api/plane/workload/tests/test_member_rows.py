# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# DB integration tests for the member-row half of the workload response
# (plans/260824-workload-unscheduled-in-today/phase-1-member-rows-api.md).
#
# Before this, `owner_ids` was a union of three estimate-keyed maps, so a
# member with no estimated work had no row at all. Two different absences
# produced that silence — no assigned work item, and assigned work items
# nobody estimated — and both are covered here, because from the reader's
# side they were never distinguishable.
#
# The assertions that matter are NOT "a row exists": several of these would
# pass on a row rendered as a second lane called "Unassigned", or on a row
# that leaked a restricted project's roster. They assert the NAME, the
# capacity, and the exclusions.

import uuid
from datetime import date

from django.test import TransactionTestCase

try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.service import compute_workload

WIN_FROM = date(2026, 1, 1)
WIN_TO = date(2026, 12, 31)


def _user(email=None, is_bot=False, display_name=None):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    u = User.objects.create_user(
        username=f"user_{uid}",
        email=email or f"u-{uid}@test.invalid",
        password="x",
        is_bot=is_bot,
    )
    if display_name:
        User.objects.filter(pk=u.pk).update(display_name=display_name)
        u.refresh_from_db()
    return u


def _ws(owner=None):
    from plane.db.models import Workspace

    slug = f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner or _user())


def _project(ws, guest_view_all_features=True):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
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


def _state(ws, proj, group="started"):
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


def _assign(ws, proj, issue, user):
    from plane.db.models import IssueAssignee

    return IssueAssignee.objects.create(
        workspace=ws, project=proj, issue=issue, assignee=user
    )


def _estimate(ws, proj, issue, hours):
    from plane.workload.models import WorkloadEstimate

    return WorkloadEstimate.objects.create(
        workspace=ws, project=proj, issue=issue, hours=hours
    )


def _run(user, ws, **kwargs):
    return compute_workload(
        user, ws.slug, "week", WIN_FROM, WIN_TO, **kwargs
    )


def _row_for(result, user):
    for row in result["rows"]:
        if row["assignee_id"] == str(user.id):
            return row
    return None


def _names(result):
    return [r["assignee_name"] for r in result["rows"]]


class TestMemberRowsAppear(TransactionTestCase):
    def test_member_with_no_assigned_work_item_gets_a_row(self):
        """The headline case: a member carrying nothing is still on the board."""
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        idle = _user(display_name="Idle Ivy")
        _pmember(ws, proj, idle)

        row = _row_for(_run(admin, ws), idle)
        self.assertIsNotNone(row, "a member with no work must still get a row")
        self.assertEqual(row["total"], 0)
        self.assertEqual(row["tasks"], [])
        self.assertEqual(row["buckets"], {})

    def test_member_whose_issues_are_all_unestimated_gets_a_row(self):
        """The second invisibility, and the reason rows are driven off the
        member list rather than off a zero-assignment query: a member with real
        work that nobody estimated is absent for a DIFFERENT reason and looks
        identical to the reader."""
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        unmeasured = _user(display_name="Unmeasured Uma")
        _pmember(ws, proj, unmeasured)
        st = _state(ws, proj)
        issue = _issue(ws, proj, st, admin, target=date(2026, 3, 2))
        _assign(ws, proj, issue, unmeasured)
        # deliberately no _estimate()

        row = _row_for(_run(admin, ws), unmeasured)
        self.assertIsNotNone(row)
        self.assertEqual(row["total"], 0)

    def test_the_row_carries_the_display_name_not_unassigned(self):
        """`assignee_name` falls back to "Unassigned" for an id `names` does not
        know, so a member id added to `owner_ids` without a name renders as a
        SECOND "Unassigned" lane. Asserting the row exists would not catch it."""
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        idle = _user(display_name="Named Nina")
        _pmember(ws, proj, idle)

        result = _run(admin, ws)
        row = _row_for(result, idle)
        self.assertEqual(row["assignee_name"], "Named Nina")
        # No member row may render as "Unassigned". That lane is reserved for
        # issues with no qualifying assignee, and there are none here — so its
        # appearance would mean a member id reached `owner_ids` without a name.
        member_names = [r["assignee_name"] for r in result["rows"] if r["assignee_id"]]
        self.assertNotIn("Unassigned", member_names)

    def test_empty_row_carries_a_full_capacity_budget(self):
        """The unused capacity IS the point of the row — an empty row with an
        empty `capacity_buckets` would say nothing about who is free."""
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        idle = _user()
        _pmember(ws, proj, idle)
        busy = _user()
        _pmember(ws, proj, busy)
        st = _state(ws, proj)
        issue = _issue(ws, proj, st, admin, target=date(2026, 3, 2))
        _assign(ws, proj, issue, busy)
        _estimate(ws, proj, issue, 5)

        result = _run(admin, ws)
        idle_row, busy_row = _row_for(result, idle), _row_for(result, busy)
        self.assertGreater(sum(idle_row["capacity_buckets"].values()), 0)
        self.assertEqual(
            idle_row["capacity_buckets"],
            busy_row["capacity_buckets"],
            "capacity is workspace-wide; an empty row must get the same budget",
        )

    def test_member_of_several_in_scope_projects_gets_exactly_one_row(self):
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        idle = _user()
        for _ in range(3):
            proj = _project(ws)
            _pmember(ws, proj, admin)
            _pmember(ws, proj, idle)

        rows = [r for r in _run(admin, ws)["rows"] if r["assignee_id"] == str(idle.id)]
        self.assertEqual(len(rows), 1)

    def test_rows_stay_alphabetical_with_unassigned_pinned_first(self):
        """Ordering is unchanged (D13) — empty and loaded members interleave."""
        admin = _user(display_name="Mid Molly")
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        for name in ("Zoe Zed", "Abe Able"):
            _pmember(ws, proj, _user(display_name=name))
        # The Unassigned lane exists only when some issue has no qualifying
        # assignee — without this the pin has nothing to pin and the test
        # would assert against a board that never contained the row.
        st = _state(ws, proj)
        orphan = _issue(ws, proj, st, admin, target=date(2026, 3, 2))
        _estimate(ws, proj, orphan, 4)

        names = _names(_run(admin, ws))
        self.assertEqual(names[0], "Unassigned")
        rest = names[1:]
        self.assertEqual(rest, sorted(rest, key=str.casefold))
        self.assertEqual(rest, ["Abe Able", "Mid Molly", "Zoe Zed"])


class TestMemberRowExclusions(TransactionTestCase):
    """Each exclusion is a way the predicate silently widens if someone later
    reaches for WorkspaceMember or drops a filter. None would be visible in a
    response anyone eyeballs."""

    def test_bot_member_gets_no_row(self):
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        bot = _user(is_bot=True, display_name="Botty")
        _pmember(ws, proj, bot)

        self.assertIsNone(_row_for(_run(admin, ws), bot))

    def test_inactive_project_member_gets_no_row(self):
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        gone = _user(display_name="Departed Dan")
        _pmember(ws, proj, gone, is_active=False)

        self.assertIsNone(_row_for(_run(admin, ws), gone))

    def test_member_of_an_out_of_scope_project_gets_no_row(self):
        """Scoping to one project must not surface the other's roster."""
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        in_scope, out_of_scope = _project(ws), _project(ws)
        _pmember(ws, in_scope, admin)
        _pmember(ws, out_of_scope, admin)
        elsewhere = _user(display_name="Elsewhere Ellie")
        _pmember(ws, out_of_scope, elsewhere)

        result = _run(admin, ws, requested_project_ids=[str(in_scope.id)])
        self.assertIsNone(_row_for(result, elsewhere))

    def test_workspace_member_with_no_project_gets_no_row(self):
        """Membership is ProjectMember, never WorkspaceMember — someone with no
        project in scope could never be assigned work this request returns, so
        their lane could never be filled."""
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        bystander = _user(display_name="Bystander Bo")
        _wmember(ws, bystander, role=15)  # workspace only, no ProjectMember

        self.assertIsNone(_row_for(_run(admin, ws), bystander))


class TestMemberRowsAndFilters(TransactionTestCase):
    def test_assignee_filter_narrows_empty_rows_too(self):
        """`assignee_filter` is applied to per-issue OWNERS and never touched
        `owner_ids`, so without an explicit intersection a request narrowed to
        one person would still carry every other member's empty lane."""
        admin = _user()
        ws = _ws(owner=admin)
        _wmember(ws, admin, role=20)
        proj = _project(ws)
        _pmember(ws, proj, admin)
        wanted = _user(display_name="Wanted Wes")
        other = _user(display_name="Other Otto")
        _pmember(ws, proj, wanted)
        _pmember(ws, proj, other)

        # uuid.UUID, not str — `views._split_uuids` is what real callers go
        # through, and the per-issue owner filter compares against UUIDs too.
        result = _run(admin, ws, assignee_ids=[wanted.id])
        self.assertIsNotNone(_row_for(result, wanted))
        self.assertIsNone(
            _row_for(result, other),
            "filtering to one member must not leave everyone else's empty lane",
        )


class TestGuestRestriction(TransactionTestCase):
    def test_flag_off_guest_does_not_see_the_project_roster(self):
        """A flag-off guest may see only their OWN issues in that project, so
        listing its members here would leak through the workload view a set of
        names the issue views refuse to show."""
        owner = _user()
        ws = _ws(owner=owner)
        proj = _project(ws, guest_view_all_features=False)
        guest = _user(display_name="Guest Gus")
        _wmember(ws, guest, role=5)
        _pmember(ws, proj, guest, role=5)
        colleague = _user(display_name="Colleague Cleo")
        _pmember(ws, proj, colleague, role=15)

        result = _run(guest, ws)
        self.assertIsNone(
            _row_for(result, colleague),
            "a restricted project's roster must not reach a flag-off guest",
        )

    def test_flag_off_guest_still_gets_their_own_row(self):
        """Their own membership is not a secret from them, and the row carries
        the capacity budget their own work is measured against."""
        owner = _user()
        ws = _ws(owner=owner)
        proj = _project(ws, guest_view_all_features=False)
        guest = _user(display_name="Guest Gus")
        _wmember(ws, guest, role=5)
        _pmember(ws, proj, guest, role=5)

        row = _row_for(_run(guest, ws), guest)
        self.assertIsNotNone(row)
        self.assertEqual(row["assignee_name"], "Guest Gus")
