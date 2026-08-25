# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Phase 7 — per-task payload + overdue flag. DB integration tests (real
# Postgres) for the `tasks` array threaded through compute_workload's
# aggregation loop. Mirrors test_workload_db.py's fixture style (explicit
# ORM rows, TransactionTestCase, no mocking the unit under test) so the two
# files stay in sync; `_resolve_today` is mocked ONLY where a test needs a
# deterministic "now" for the workspace-timezone overdue derivation.

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

# Run Celery tasks inline (no broker in tests). Issue creation enqueues an
# activity task; eager + non-propagating means it runs without a broker and a
# failure inside it never breaks the unit under test.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.service import WORKLOAD_MAX_TASKS_PER_ASSIGNEE, compute_workload

WIN_FROM = date(2026, 1, 1)
WIN_TO = date(2026, 12, 31)


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_workload_db.py so the two files stay in sync)
# ---------------------------------------------------------------------------


def _ws(slug=None, timezone_name="UTC"):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    owner = _user()
    return Workspace.objects.create(
        name=slug, slug=slug, logo="", owner=owner, timezone=timezone_name
    )


def _user(email=None, is_bot=False, display_name=None):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    email = email or f"u-{uid}@test.invalid"
    user = User.objects.create_user(
        username=f"user_{uid}", email=email, password="x", is_bot=is_bot
    )
    # `User.save()` derives `display_name` from the email when it is blank, so
    # a test that asserts on ROW ORDER has to set it explicitly — otherwise
    # every name is a random hex slug and any ordering assertion is luck.
    if display_name is not None:
        User.objects.filter(pk=user.pk).update(display_name=display_name)
        user.refresh_from_db()
    return user


def _project(ws, identifier=None):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=identifier or uuid.uuid4().hex[:5].upper(),
    )


def _pmember(ws, proj, user, role=15, is_active=True):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(
        workspace=ws, project=proj, member=user, role=role, is_active=is_active
    )


def _state(ws, proj, group, name=None, color="#fff"):
    from plane.db.models import State

    # `name`/`color` are overridable so a test can pin what the timeline
    # actually paints with. `State.color` is a plain CharField with no hex
    # validation, so `color=""` is a REACHABLE production value, not a
    # contrived one — see test_blank_state_colour_emits_empty_string.
    return State.objects.create(
        workspace=ws, project=proj,
        name=name if name is not None else f"{group}-{uuid.uuid4().hex[:4]}",
        color=color, group=group,
    )


def _issue(ws, proj, state, created_by, start=None, target=None, name=None):
    from plane.db.models import Issue

    # NOTE: `Issue.save()` ALWAYS overwrites `sequence_id` with the next
    # per-project auto-increment on create (apps/api/plane/db/models/issue.py)
    # regardless of what is passed in — so it is never accepted as a kwarg
    # here. Assertions that need the identifier read `issue.sequence_id` back
    # off the object `.create()` returns (already mutated in place by save()).
    return Issue.objects.create(
        workspace=ws, project=proj, name=name or f"i-{uuid.uuid4().hex[:6]}",
        created_by=created_by, state=state, start_date=start, target_date=target,
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
    return next(r for r in data["rows"] if r["assignee_id"] == str(user.id))


class TestTaskAppearsOnRightAssignee(TransactionTestCase):
    def test_task_row_fields_and_assignee_scoping(self):
        ws = _ws()
        proj = _project(ws, identifier="PLANE")
        # An explicit name + a NON-default colour: the default "#fff" would
        # pass even if the value were hard-coded rather than read off the row.
        st = _state(ws, proj, "started", name="In Review", color="#8b5cf6")
        u1 = _user()
        u2 = _user()
        _pmember(ws, proj, u1)
        _pmember(ws, proj, u2)

        monday = date(2026, 6, 15)
        issue = _issue(
            ws, proj, st, u1, start=monday, target=monday,
            name="Fix feedback release 1",
        )
        _assign(ws, proj, issue, u1, created_at=_t(1))
        _estimate(ws, proj, issue, 8.0)

        # A second, unrelated task owned by u2 must never leak into u1's row.
        issue2 = _issue(ws, proj, st, u2, start=monday, target=monday)
        _assign(ws, proj, issue2, u2, created_at=_t(1))
        _estimate(ws, proj, issue2, 3.0)

        data = compute_workload(u1, ws.slug, "day", WIN_FROM, WIN_TO)
        row1 = _rowfor(data, u1)
        row2 = _rowfor(data, u2)

        self.assertEqual(len(row1["tasks"]), 1)
        task = row1["tasks"][0]
        self.assertEqual(task["id"], str(issue.id))
        # `project_id` is what lets the UI build a work-item link / open the
        # peek panel — the identifier string is for display, never for routing.
        self.assertEqual(task["project_id"], str(proj.id))
        self.assertEqual(task["identifier"], f"PLANE-{issue.sequence_id}")
        self.assertEqual(task["name"], "Fix feedback release 1")
        self.assertEqual(task["hours"], 8.0)
        self.assertEqual(task["start_date"], "2026-06-15")
        self.assertEqual(task["target_date"], "2026-06-15")
        self.assertEqual(task["state_group"], "started")
        # The timeline paints the bar with `state_color` and names it in the
        # tooltip with `state_name`. Both ride the `state` JOIN that
        # `state_group` above already forces.
        self.assertEqual(task["state_name"], "In Review")
        self.assertEqual(task["state_color"], "#8b5cf6")
        self.assertFalse(row1["tasks_truncated"])

        # u2's row carries only u2's task.
        self.assertEqual([t["id"] for t in row2["tasks"]], [str(issue2.id)])


class TestStateColourFallbackShape(TransactionTestCase):
    def test_blank_state_colour_emits_empty_string(self):
        """A blank `State.color` must serialise as "", never None.

        `State.color` is `CharField(max_length=255)` with no hex validation,
        so a blank value is reachable in production. The client's fallback
        chain (`stateBarColor`) tests one empty shape; emitting None here
        would force it to test two, and a `null` reaching
        `style={{ backgroundColor }}` renders a transparent — invisible — bar
        rather than falling back to the state-group colour.
        """
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started", name="", color="")
        u = _user()
        _pmember(ws, proj, u)

        monday = date(2026, 6, 15)
        issue = _issue(ws, proj, st, u, start=monday, target=monday)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 4.0)

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        task = _rowfor(data, u)["tasks"][0]

        self.assertEqual(task["state_color"], "")
        self.assertEqual(task["state_name"], "")
        self.assertIsNotNone(task["state_color"])
        self.assertIsNotNone(task["state_name"])


class TestUnscheduledTask(TransactionTestCase):
    def test_unscheduled_task_has_null_target_date(self):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        u = _user()
        _pmember(ws, proj, u)

        # No target -> all-unscheduled per spread_estimate; must still
        # surface as a `tasks` row with target_date null (phase-7.md
        # response shape: "may be null -> unscheduled").
        issue = _issue(ws, proj, st, u, start=None, target=None)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 5.0)

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        row = _rowfor(data, u)
        self.assertEqual(len(row["tasks"]), 1)
        task = row["tasks"][0]
        self.assertIsNone(task["start_date"])
        self.assertIsNone(task["target_date"])
        self.assertEqual(task["hours"], 5.0)
        self.assertFalse(task["overdue"])  # no target -> never overdue

    def test_span_entirely_outside_window_is_not_a_task(self):
        """A dated (non-null-target) issue whose whole span falls outside the
        requested window contributes no buckets AND should not appear in
        `tasks` — Phase 8's timeline has no window to plot it in."""
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        u = _user()
        _pmember(ws, proj, u)

        far_past = date(2020, 1, 1)
        issue = _issue(ws, proj, st, u, start=far_past, target=far_past)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 5.0)

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        # `u` is an active project member, so they now get a row whether or not
        # they carry anything (see `_scope_member_ids`). That row's EMPTINESS is
        # what this test is about — asserting `rows == []` used it as a proxy
        # for "the far-past issue contributed nothing", which stopped being the
        # same statement once every member got a lane. Assert the subject
        # directly instead: the issue is absent from `tasks`, from the hours,
        # and from the counted set.
        # `_rowfor` raises when the row is absent, so a missing row fails here
        # loudly rather than sliding into an assertIsNotNone that cannot fire.
        row = _rowfor(data, u)
        self.assertEqual(row["tasks"], [], "the out-of-window issue must not be a task")
        self.assertEqual(row["total"], 0)
        # `issues_counted` is incremented BEFORE the window clip (right after
        # `spread_estimate`), so this far-past issue IS counted even though it
        # produced no bucket and no task. Not an inconsistency — it is the fact
        # the timeline's empty-state overlay relies on to tell "N items exist,
        # widen your range" apart from "nothing is estimated at all". This
        # fixture is precisely that case: no work on screen, one item counted.
        self.assertEqual(data["meta"]["issues_counted"], 1)


class TestOverdueFlag(TransactionTestCase):
    def _setup(self, group):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, group)
        u = _user()
        _pmember(ws, proj, u)
        return ws, proj, st, u

    def test_overdue_flips_true_for_open_state_past_target(self):
        ws, proj, st, u = self._setup("started")
        past = date(2026, 1, 5)
        issue = _issue(ws, proj, st, u, start=past, target=past)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 2.0)

        # Freeze "now" well after `past`, in the workspace's own tz (UTC).
        frozen_now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        with patch("plane.workload.service.dj_timezone.now", return_value=frozen_now):
            data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)

        task = _rowfor(data, u)["tasks"][0]
        self.assertTrue(task["overdue"])

    def test_overdue_stays_false_for_completed_state(self):
        ws, proj, st, u = self._setup("completed")
        past = date(2026, 1, 5)
        issue = _issue(ws, proj, st, u, start=past, target=past)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 2.0)

        frozen_now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        with patch("plane.workload.service.dj_timezone.now", return_value=frozen_now):
            data = compute_workload(
                u, ws.slug, "day", WIN_FROM, WIN_TO, state_groups=["completed"]
            )

        task = _rowfor(data, u)["tasks"][0]
        self.assertFalse(task["overdue"])

    def test_overdue_stays_false_for_cancelled_state(self):
        ws, proj, st, u = self._setup("cancelled")
        past = date(2026, 1, 5)
        issue = _issue(ws, proj, st, u, start=past, target=past)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 2.0)

        frozen_now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        with patch("plane.workload.service.dj_timezone.now", return_value=frozen_now):
            data = compute_workload(
                u, ws.slug, "day", WIN_FROM, WIN_TO, state_groups=["cancelled"]
            )

        task = _rowfor(data, u)["tasks"][0]
        self.assertFalse(task["overdue"])

    def test_overdue_stays_false_for_future_target(self):
        ws, proj, st, u = self._setup("started")
        future = date(2026, 12, 1)
        issue = _issue(ws, proj, st, u, start=future, target=future)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 2.0)

        frozen_now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        with patch("plane.workload.service.dj_timezone.now", return_value=frozen_now):
            data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)

        task = _rowfor(data, u)["tasks"][0]
        self.assertFalse(task["overdue"])


class TestOverdueTimezoneResolution(TransactionTestCase):
    """`today` must be resolved in the WORKSPACE's own timezone (core's
    `Workspace.timezone` field), not the server's/UTC's — a task must not
    become overdue (or not) purely because of a UTC day rollover.
    """

    def test_same_instant_different_workspace_timezone_disagrees_on_overdue(self):
        # Frozen instant: 2026-06-15 00:30 UTC.
        #   - In UTC itself, "today" is 2026-06-15.
        #   - In Pacific/Honolulu (UTC-10), local time is 2026-06-14 14:30,
        #     so "today" there is still 2026-06-14 — one calendar day earlier.
        frozen_now = datetime(2026, 6, 15, 0, 30, tzinfo=timezone.utc)

        ws_utc = _ws(timezone_name="UTC")
        ws_honolulu = _ws(timezone_name="Pacific/Honolulu")

        proj_utc = _project(ws_utc)
        proj_hono = _project(ws_honolulu)
        st_utc = _state(ws_utc, proj_utc, "started")
        st_hono = _state(ws_honolulu, proj_hono, "started")
        u_utc = _user()
        u_hono = _user()
        _pmember(ws_utc, proj_utc, u_utc)
        _pmember(ws_honolulu, proj_hono, u_hono)

        # target_date = 2026-06-14 -> already in the past for UTC's "today"
        # (6/15) but IS "today" for Honolulu (6/14) -> not overdue there.
        target = date(2026, 6, 14)
        issue_utc = _issue(ws_utc, proj_utc, st_utc, u_utc, start=target, target=target)
        _assign(ws_utc, proj_utc, issue_utc, u_utc, created_at=_t(1))
        _estimate(ws_utc, proj_utc, issue_utc, 2.0)

        issue_hono = _issue(ws_honolulu, proj_hono, st_hono, u_hono, start=target, target=target)
        _assign(ws_honolulu, proj_hono, issue_hono, u_hono, created_at=_t(1))
        _estimate(ws_honolulu, proj_hono, issue_hono, 2.0)

        with patch("plane.workload.service.dj_timezone.now", return_value=frozen_now):
            data_utc = compute_workload(u_utc, ws_utc.slug, "day", WIN_FROM, WIN_TO)
            data_hono = compute_workload(u_hono, ws_honolulu.slug, "day", WIN_FROM, WIN_TO)

        self.assertTrue(_rowfor(data_utc, u_utc)["tasks"][0]["overdue"])
        self.assertFalse(_rowfor(data_hono, u_hono)["tasks"][0]["overdue"])

    def test_missing_workspace_row_or_unknown_timezone_falls_back_to_utc(self):
        """Defensive fallback: an unrecognised stored timezone string must
        not raise — it degrades to UTC rather than a 500."""
        ws = _ws(timezone_name="UTC")
        proj = _project(ws)
        st = _state(ws, proj, "started")
        u = _user()
        _pmember(ws, proj, u)

        from plane.db.models import Workspace

        # Bypass the model's choices validation (direct .update, no .full_clean())
        # to simulate a corrupt/legacy stored value.
        Workspace.objects.filter(pk=ws.pk).update(timezone="Not/A_Real_Zone")

        past = date(2026, 1, 5)
        issue = _issue(ws, proj, st, u, start=past, target=past)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 2.0)

        frozen_now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        with patch("plane.workload.service.dj_timezone.now", return_value=frozen_now):
            data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)  # must not raise

        task = _rowfor(data, u)["tasks"][0]
        self.assertTrue(task["overdue"])  # UTC fallback: 1/5 < 6/1


class TestTruncation(TransactionTestCase):
    def test_truncation_caps_tasks_and_sets_flag_per_row(self):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        u_many = _user()
        u_few = _user()
        _pmember(ws, proj, u_many)
        _pmember(ws, proj, u_few)

        # One row well past the cap...
        for i in range(WORKLOAD_MAX_TASKS_PER_ASSIGNEE + 5):
            d = date(2026, 1, 1) + timedelta(days=i % 300)
            issue = _issue(ws, proj, st, u_many, start=d, target=d)
            _assign(ws, proj, issue, u_many, created_at=_t(1))
            _estimate(ws, proj, issue, 1.0)

        # ...and one row well under it, in the SAME response.
        d = date(2026, 6, 1)
        issue_few = _issue(ws, proj, st, u_few, start=d, target=d)
        _assign(ws, proj, issue_few, u_few, created_at=_t(1))
        _estimate(ws, proj, issue_few, 1.0)

        data = compute_workload(u_many, ws.slug, "day", WIN_FROM, WIN_TO)
        row_many = _rowfor(data, u_many)
        row_few = _rowfor(data, u_few)

        self.assertEqual(len(row_many["tasks"]), WORKLOAD_MAX_TASKS_PER_ASSIGNEE)
        self.assertTrue(row_many["tasks_truncated"])
        # The flag is per-row — an untruncated sibling row must read False,
        # not inherit the truncated row's flag (a workspace-wide flag would
        # be a bug: it would flag every assignee as truncated).
        self.assertEqual(len(row_few["tasks"]), 1)
        self.assertFalse(row_few["tasks_truncated"])


class TestSpanContributesToMultipleBuckets(TransactionTestCase):
    def test_three_day_span_is_one_task_and_three_buckets(self):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        u = _user()
        _pmember(ws, proj, u)

        start = date(2026, 6, 15)  # Monday
        target = date(2026, 6, 17)  # Wednesday — 3 workdays
        issue = _issue(ws, proj, st, u, start=start, target=target)
        _assign(ws, proj, issue, u, created_at=_t(1))
        _estimate(ws, proj, issue, 9.0)

        data = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        row = _rowfor(data, u)

        # Exactly one task row for the issue...
        self.assertEqual(len(row["tasks"]), 1)
        self.assertEqual(row["tasks"][0]["hours"], 9.0)  # whole estimate, not a slice
        # ...but the windowed spread still lands on 3 separate day buckets.
        self.assertEqual(
            {"2026-06-15", "2026-06-16", "2026-06-17"}, set(row["buckets"].keys())
        )
        self.assertAlmostEqual(sum(row["buckets"].values()), 9.0, places=2)


class TestNoNPlusOne(TransactionTestCase):
    def test_task_detail_columns_add_no_extra_queries_per_issue(self):
        """The per-issue detail (name/identifier/state_group) that feeds
        `tasks` must come from the SAME query the aggregation already runs —
        never a per-issue fetch. Proven by comparing query counts between a
        few-task and a many-task run of the identical code path, using
        `assertNumQueries` (phase-7.md success criteria: verify, don't
        inspect)."""
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        u = _user()
        _pmember(ws, proj, u)

        def _make_issues(n):
            for i in range(n):
                d = date(2026, 1, 1) + timedelta(days=i)
                issue = _issue(ws, proj, st, u, start=d, target=d)
                _assign(ws, proj, issue, u, created_at=_t(1))
                _estimate(ws, proj, issue, 1.0)

        _make_issues(2)
        with CaptureQueriesContext(connection) as few_ctx:
            data_few = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        baseline = len(few_ctx.captured_queries)
        self.assertEqual(len(_rowfor(data_few, u)["tasks"]), 2)

        # Add many more issues for the SAME assignee — if task-row assembly
        # were doing a per-issue lookup, this would blow the query count up
        # proportionally to the new issue count.
        _make_issues(25)

        with self.assertNumQueries(baseline):
            data_many = compute_workload(u, ws.slug, "day", WIN_FROM, WIN_TO)
        self.assertEqual(len(_rowfor(data_many, u)["tasks"]), 27)


class TestRowOrdering(TransactionTestCase):
    """`rows` is ordered for a reader scanning for a name, not for a manager
    scanning for the busiest person: `Unassigned` first, then ascending by
    `assignee_name` case-insensitively.

    The fixture is built so the two orderings genuinely DISAGREE — the
    early-alphabet member carries the SMALLEST load and the late-alphabet
    member the largest. Under the previous `-total` sort these assertions
    fail; a fixture where load and name happen to agree would pass either way
    and prove nothing.
    """

    def test_unassigned_first_then_case_insensitive_alphabetical(self):
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        # Named on purpose. `author` carries no work of their own, and every
        # active member now gets a row — so this fixture also proves the D13
        # property that empty and loaded rows INTERLEAVE alphabetically rather
        # than being grouped. An auto-generated `u-xxxxxxxx` name would make
        # the expected list non-deterministic.
        author = _user(display_name="Author Ann")
        _pmember(ws, proj, author)

        # Mixed case on purpose: a case-SENSITIVE sort would put every
        # capitalised name ahead of every lowercase one, so "Zulu" would
        # precede "alpha" and this test would catch it.
        alpha = _user(display_name="alpha")
        Mike = _user(display_name="Mike")
        Zulu = _user(display_name="Zulu")
        for u in (alpha, Mike, Zulu):
            _pmember(ws, proj, u)

        day = date(2026, 6, 15)

        def _task(assignee, hours):
            issue = _issue(ws, proj, st, author, start=day, target=day)
            if assignee is not None:
                _assign(ws, proj, issue, assignee, created_at=_t(1))
            _estimate(ws, proj, issue, hours)

        # Load runs OPPOSITE to the alphabet.
        _task(alpha, 1.0)
        _task(Mike, 5.0)
        _task(Zulu, 20.0)
        # An issue with no active assignee produces the `Unassigned` row.
        _task(None, 3.0)

        data = compute_workload(author, ws.slug, "day", WIN_FROM, WIN_TO)
        names = [r["assignee_name"] for r in data["rows"]]

        self.assertIsNone(data["rows"][0]["assignee_id"])
        # "Author Ann" sits between "alpha" and "Mike" and carries NO work —
        # an empty row placed by name, among loaded ones.
        self.assertEqual(names, ["Unassigned", "alpha", "Author Ann", "Mike", "Zulu"])
        self.assertEqual(_rowfor(data, author)["total"], 0)

        # Restate the two properties independently of the literal list above,
        # so a future fixture change cannot quietly weaken the test.
        rest = data["rows"][1:]
        self.assertEqual(
            [r["assignee_name"] for r in rest],
            sorted((r["assignee_name"] for r in rest), key=str.casefold),
        )
        self.assertGreater(
            _rowfor(data, Zulu)["total"], _rowfor(data, alpha)["total"]
        )

    def test_a_member_named_unassigned_is_not_pinned(self):
        """The pin is keyed on `assignee_id is None`, not on the display name,
        so a real member called "Unassigned" sorts under U like anyone else."""
        ws = _ws()
        proj = _project(ws)
        st = _state(ws, proj, "started")
        author = _user(display_name="Author Ann")
        _pmember(ws, proj, author)

        impostor = _user(display_name="Unassigned")
        alpha = _user(display_name="alpha")
        for u in (impostor, alpha):
            _pmember(ws, proj, u)

        day = date(2026, 6, 15)
        for assignee in (impostor, alpha):
            issue = _issue(ws, proj, st, author, start=day, target=day)
            _assign(ws, proj, issue, assignee, created_at=_t(1))
            _estimate(ws, proj, issue, 2.0)

        data = compute_workload(author, ws.slug, "day", WIN_FROM, WIN_TO)

        # No genuinely-unassigned work here, so nothing is pinned and the
        # impostor sorts after "alpha" on name alone. `author` is present and
        # empty — every active member gets a row now — which is why the list
        # carries three names rather than two.
        self.assertEqual(
            [r["assignee_name"] for r in data["rows"]],
            ["alpha", "Author Ann", "Unassigned"],
        )
        # The property, stated independently of the literal list: nothing is
        # pinned, because no row is genuinely unassigned.
        self.assertTrue(all(r["assignee_id"] is not None for r in data["rows"]))
        self.assertIsNotNone(data["rows"][-1]["assignee_id"])
