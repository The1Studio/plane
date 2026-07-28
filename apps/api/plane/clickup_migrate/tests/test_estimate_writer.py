# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Phase 5 of the SP1 hour-estimate ETL plan
# (plane-deploy/plans/SP1-clickup-estimate-etl.md).
#
# Unit + DB-backed tests for `write_workload_estimate()` / `_parse_ms_estimate()`
# in `clickup_migrate/writers.py`:
#   1. Leaf write — row created, hours correct, authorship set.
#   2. Parent skip — no row for a parent's own estimate + ledger note; plus an
#      integration-style test proving `workload.rollup.parent_issue_ids()` (the
#      real leaf predicate pass-3 uses) agrees on parent-vs-leaf.
#   3. ms -> hours rounding, including the sub-minute edge case.
#   4. MAX_HOURS clamp.
#   5. Value-shape handling (numeric str / None / 0), plus a direct unit test
#      of `_parse_ms_estimate`.
#   6. Re-run idempotency — one row, second call is an update.
#   7. `created_by`-not-NULL regression guard (echoes PR #2/#3).
#
# Fixture style mirrors `test_writers.py` (hand-rolled `_make_*` helpers,
# `django.test.TestCase`, DB-backed) — this app does NOT use factory-boy.
# `_make_issue` additionally mirrors `workload/tests/test_rollup.py::_issue`
# (direct `Issue.objects.create`, no `write_issue()` ETL path) since the
# writer under test consumes real `Issue` instances with `parent` set.

import uuid

from django.test import SimpleTestCase, TestCase

from plane.clickup_migrate.models import MigrationRecord, MigrationRun
from plane.clickup_migrate.writers import (
    UserCache,
    _parse_ms_estimate,
    write_workload_estimate,
)
from plane.workload.aggregation import MAX_HOURS
from plane.workload.models import WorkloadEstimate


# ─────────────────────────────────────────────────────────────────────
# Helpers (mirror test_writers.py's hand-rolled `_make_*` fixtures)
# ─────────────────────────────────────────────────────────────────────

def _unique_email(prefix="user"):
    return f"{prefix}+{uuid.uuid4().hex[:8]}@test.example"


def _make_user(email=None, is_bot=False):
    """Create a minimal Plane User."""
    from plane.db.models import User
    email = email or _unique_email("bot" if is_bot else "user")
    return User.objects.create_user(
        email=email,
        password="testpass",
        username=email,
    )


def _make_workspace(owner):
    from plane.db.models import Workspace
    slug = f"ws-{uuid.uuid4().hex[:8]}"
    ws = Workspace.objects.create(name="Test WS", slug=slug, owner=owner)
    ws.save(created_by_id=owner.id, disable_auto_set_user=True)
    return ws


def _make_project(workspace, bot_user):
    from plane.db.models import Project, ProjectIdentifier
    identifier = uuid.uuid4().hex[:6].upper()
    project = Project.objects.create(
        name="Test Project",
        identifier=identifier,
        workspace=workspace,
        network=2,
    )
    project.save(created_by_id=bot_user.id, disable_auto_set_user=True)
    ProjectIdentifier.objects.get_or_create(
        project=project,
        defaults={"workspace": workspace, "name": identifier},
    )
    return project


def _make_state(project, workspace, bot_user, group="unstarted"):
    from plane.db.models import State
    state = State.objects.create(
        project=project,
        workspace=workspace,
        name=f"State-{uuid.uuid4().hex[:4]}",
        color="#aabbcc",
        group=group,
        default=True,
    )
    state.save(created_by_id=bot_user.id, disable_auto_set_user=True)
    return state


def _make_run():
    return MigrationRun.objects.create(status="pending")


def _make_issue(workspace, project, state=None, parent=None):
    """Build an Issue row directly (mirrors workload/tests/test_rollup.py::_issue).

    The writer under test consumes real Issue instances (with `parent` set for
    the leaf/parent integration test) — not the `write_issue()` ETL path, so a
    direct `Issue.objects.create` is the right-shaped fixture here.
    """
    from plane.db.models import Issue
    return Issue.objects.create(
        workspace=workspace,
        project=project,
        name=f"issue-{uuid.uuid4().hex[:6]}",
        state=state,
        parent=parent,
        sequence_id=1,
    )


# ─────────────────────────────────────────────────────────────────────
# Case 5 (partial) — `_parse_ms_estimate` direct unit coverage
# ─────────────────────────────────────────────────────────────────────

class TestParseMsEstimate(SimpleTestCase):
    """Direct unit coverage for the defensive ms-parse helper (Phase 1).
    No DB required — pure value coercion."""

    def test_int_passthrough(self):
        self.assertEqual(_parse_ms_estimate(3_600_000), 3_600_000)

    def test_numeric_string_is_parsed(self):
        self.assertEqual(_parse_ms_estimate("3600000"), 3600000)

    def test_none_returns_none(self):
        self.assertIsNone(_parse_ms_estimate(None))

    def test_zero_returns_none(self):
        self.assertIsNone(_parse_ms_estimate(0))

    def test_negative_returns_none(self):
        self.assertIsNone(_parse_ms_estimate(-5))

    def test_unparseable_string_returns_none(self):
        self.assertIsNone(_parse_ms_estimate("abc"))


# ─────────────────────────────────────────────────────────────────────
# Shared DB-backed fixture base
# ─────────────────────────────────────────────────────────────────────

class _EstimateWriterTestBase(TestCase):
    def setUp(self):
        self.bot_user = _make_user(is_bot=True)
        self.workspace = _make_workspace(self.bot_user)
        self.project = _make_project(self.workspace, self.bot_user)
        self.state = _make_state(self.project, self.workspace, self.bot_user)
        self.run = _make_run()

    def _user_cache(self):
        return UserCache(self.bot_user)

    def _issue(self, parent=None):
        return _make_issue(self.workspace, self.project, state=self.state, parent=parent)


# ─────────────────────────────────────────────────────────────────────
# Case 1 — Leaf write
# ─────────────────────────────────────────────────────────────────────

class TestLeafWrite(_EstimateWriterTestBase):
    def test_leaf_write_creates_row_with_correct_hours_and_authorship(self):
        issue = self._issue()
        task_id = f"cu-est-{uuid.uuid4().hex[:8]}"

        token = write_workload_estimate(
            self.run, issue, task_id, 3_600_000, True, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "created")
        qs = WorkloadEstimate.objects.filter(issue=issue)
        self.assertEqual(qs.count(), 1)
        est = qs.get()
        self.assertEqual(est.hours, 1.0)
        self.assertEqual(est.created_by_id, self.bot_user.id)
        self.assertEqual(est.workspace_id, issue.workspace_id)
        self.assertEqual(est.project_id, issue.project_id)


# ─────────────────────────────────────────────────────────────────────
# Case 2 — Parent skip
# ─────────────────────────────────────────────────────────────────────

class TestParentSkip(_EstimateWriterTestBase):
    def test_parent_with_own_estimate_is_skipped_no_row(self):
        parent_issue = self._issue()
        self._issue(parent=parent_issue)  # a countable child makes parent_issue a parent
        task_id = f"cu-parent-{uuid.uuid4().hex[:8]}"

        token = write_workload_estimate(
            self.run, parent_issue, task_id, 7_200_000, False, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "skipped-parent")
        self.assertEqual(WorkloadEstimate.objects.filter(issue=parent_issue).count(), 0)

        record = MigrationRecord.objects.get(
            run=self.run,
            plane_type="WorkloadEstimate",
            status=MigrationRecord.STATUS_SKIPPED,
            source_id=task_id,
        )
        self.assertIn("parent", record.error.lower())

    def test_parent_issue_ids_confirms_leafness_via_rollup(self):
        """Integration proof: the real leaf predicate (workload.rollup.parent_issue_ids
        — the batched predicate pass-3 uses to compute `is_leaf` BEFORE calling the
        writer) agrees that `parent_issue` (has a countable child) is a parent and
        `child_issue` (no countable children) is a leaf."""
        from plane.workload.rollup import parent_issue_ids

        parent_issue = self._issue()
        child_issue = self._issue(parent=parent_issue)

        parents = parent_issue_ids([parent_issue.id, child_issue.id])

        self.assertIn(parent_issue.id, parents)
        self.assertNotIn(child_issue.id, parents)


# ─────────────────────────────────────────────────────────────────────
# Case 3 — ms -> hours rounding
# ─────────────────────────────────────────────────────────────────────

class TestMsToHoursRounding(_EstimateWriterTestBase):
    def test_5_400_000_ms_rounds_to_1_5_hours(self):
        issue = self._issue()

        token = write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", 5_400_000, True, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "created")
        est = WorkloadEstimate.objects.get(issue=issue)
        self.assertEqual(est.hours, 1.5)

    def test_sub_minute_estimate_writes_zero_hours_row(self):
        """1_000 ms is a positive, parseable value -> `_parse_ms_estimate` does NOT
        return None, so this is NOT the "skipped-zero" path (that token is reserved
        for None/0/negative/unparseable raw values). round(1_000 / 3_600_000, 2)
        == 0.0, so a row IS written with hours == 0.0.

        ASSUMPTION flagged for reconciliation with the writer author: if
        `write_workload_estimate` instead special-cases a rounds-to-zero result as
        "skipped-zero" (no row), this assertion must flip to
        `token == "skipped-zero"` + no row. As specified in the Phase-2 plan
        (`_parse_ms_estimate` only maps None/0/negative/unparseable to None), the
        behavior asserted here — a written zero-hour row — is the contract-correct
        one; the plan's Phase-2 pseudocode has no rounds-to-zero special case.
        """
        issue = self._issue()

        token = write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", 1_000, True, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "created")
        est = WorkloadEstimate.objects.get(issue=issue)
        self.assertEqual(est.hours, 0.0)


# ─────────────────────────────────────────────────────────────────────
# Case 4 — MAX_HOURS clamp
# ─────────────────────────────────────────────────────────────────────

class TestMaxHoursClamp(_EstimateWriterTestBase):
    def test_estimate_above_max_hours_is_clamped(self):
        issue = self._issue()
        raw_ms = (MAX_HOURS + 5000) * 3_600_000

        token = write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", raw_ms, True, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "clamped")
        est = WorkloadEstimate.objects.get(issue=issue)
        self.assertEqual(est.hours, MAX_HOURS)


# ─────────────────────────────────────────────────────────────────────
# Case 5 — Value-shape handling (DB-backed half; pure-parse half is above)
# ─────────────────────────────────────────────────────────────────────

class TestValueShape(_EstimateWriterTestBase):
    def test_numeric_string_estimate_creates_row(self):
        issue = self._issue()

        token = write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", "3600000", True, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "created")
        est = WorkloadEstimate.objects.get(issue=issue)
        self.assertEqual(est.hours, 1.0)

    def test_none_estimate_is_skipped_zero_no_row(self):
        issue = self._issue()

        token = write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", None, True, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "skipped-zero")
        self.assertEqual(WorkloadEstimate.objects.filter(issue=issue).count(), 0)

    def test_zero_estimate_is_skipped_zero_no_row(self):
        issue = self._issue()

        token = write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", 0, True, self._user_cache(), dry_run=False,
        )

        self.assertEqual(token, "skipped-zero")
        self.assertEqual(WorkloadEstimate.objects.filter(issue=issue).count(), 0)


# ─────────────────────────────────────────────────────────────────────
# Case 6 — Re-run idempotency
# ─────────────────────────────────────────────────────────────────────

class TestReRunIdempotency(_EstimateWriterTestBase):
    def test_writing_the_same_leaf_twice_produces_exactly_one_row(self):
        issue = self._issue()
        task_id = f"cu-idem-{uuid.uuid4().hex[:8]}"
        user_cache = self._user_cache()

        first_token = write_workload_estimate(
            self.run, issue, task_id, 3_600_000, True, user_cache, dry_run=False,
        )
        second_token = write_workload_estimate(
            self.run, issue, task_id, 3_600_000, True, user_cache, dry_run=False,
        )

        self.assertIn(first_token, ("created", "updated"))
        self.assertEqual(second_token, "updated")
        self.assertEqual(WorkloadEstimate.objects.filter(issue=issue).count(), 1)


# ─────────────────────────────────────────────────────────────────────
# Case 7 — created_by-not-NULL regression guard (echoes PR #2/#3)
# ─────────────────────────────────────────────────────────────────────

class TestCreatedByRegressionGuard(_EstimateWriterTestBase):
    def test_created_by_is_not_null_after_leaf_write(self):
        """WorkloadEstimate is a plain models.Model with an explicit nullable
        `created_by` FK and no BaseModel auto-set-user hook — the writer must set
        `created_by=user_cache.bot_user` directly in `update_or_create(defaults=)`.
        Regression guard for the same class of bug as PR #2/#3 (write_issue
        authorship left NULL when the wrong save-path was cargo-culted)."""
        issue = self._issue()

        write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", 3_600_000, True, self._user_cache(), dry_run=False,
        )

        est = WorkloadEstimate.objects.get(issue=issue)
        self.assertIsNotNone(est.created_by_id)


# ─────────────────────────────────────────────────────────────────────
# Case 8 — dry-run must not write, but must still tally (--plan contract)
# ─────────────────────────────────────────────────────────────────────

class TestDryRun(_EstimateWriterTestBase):
    """--plan runs the estimate pass with dry_run=True. Contract: NO DB write
    of any kind (WorkloadEstimate OR MigrationRecord), but the returned token
    must still be the would-be status so the --plan summary counts leaves and
    hours correctly (mirrors write_subtask_parent's dry-run-returns-True idiom)."""

    def test_leaf_dry_run_returns_would_be_token_and_writes_no_row(self):
        issue = self._issue()

        token = write_workload_estimate(
            self.run, issue, f"cu-{uuid.uuid4().hex[:8]}", 3_600_000, True, self._user_cache(), dry_run=True,
        )

        # would-be status so --plan tallies it as "written"
        self.assertEqual(token, "created")
        self.assertEqual(WorkloadEstimate.objects.filter(issue=issue).count(), 0)

    def test_parent_skip_dry_run_writes_no_migration_record(self):
        parent_issue = self._issue()
        self._issue(parent=parent_issue)  # countable child → parent_issue is a parent
        task_id = f"cu-parent-{uuid.uuid4().hex[:8]}"
        before = MigrationRecord.objects.count()

        token = write_workload_estimate(
            self.run, parent_issue, task_id, 7_200_000, False, self._user_cache(), dry_run=True,
        )

        self.assertEqual(token, "skipped-parent")
        # dry-run must not ledger anything (regression guard: the parent-skip
        # MigrationRecord write was previously unconditional)
        self.assertEqual(MigrationRecord.objects.count(), before)


# ─────────────────────────────────────────────────────────────────────
# Case 8 — Ledger key collision (issue #7)
# ─────────────────────────────────────────────────────────────────────

class TestLedgerKeyDoesNotCollideWithIssue(_EstimateWriterTestBase):
    """A ClickUp task ledgers twice: once as an Issue, once as a WorkloadEstimate.

    MigrationRecord is unique_together ("run", "source_type", "source_id"), so
    both writers using source_type="task" made pass-3 (estimates) overwrite the
    Issue row pass-1 wrote. That silently broke every
    _ledger_done(run, "task", <task_id>) lookup on a RESUMED run — pass-2
    (write_subtask_parent / write_issue_relation) would resolve a
    WorkloadEstimate id, match no Issue, and drop the link while returning True.
    """

    def test_estimate_ledger_row_does_not_overwrite_issue_ledger_row(self):
        from plane.clickup_migrate.writers import (
            SOURCE_TYPE_TASK,
            SOURCE_TYPE_TASK_ESTIMATE,
            _ledger_done,
            _record_upsert,
        )

        issue = self._issue()
        task_id = f"cu-collide-{uuid.uuid4().hex[:8]}"

        # pass-1: write_issue ledgers the Issue under "task".
        _record_upsert(
            self.run, SOURCE_TYPE_TASK, task_id, "Issue", str(issue.id),
            MigrationRecord.STATUS_CREATED,
        )

        # pass-3: the estimate ledgers the SAME ClickUp task id.
        token = write_workload_estimate(
            self.run, issue, task_id, 3_600_000, True, self._user_cache(), dry_run=False,
        )
        self.assertEqual(token, "created")

        # Both rows must coexist under distinct source_types.
        self.assertEqual(
            MigrationRecord.objects.filter(run=self.run, source_id=task_id).count(), 2
        )

        # The Issue lookup pass-2 relies on must still resolve to the Issue.
        self.assertEqual(_ledger_done(self.run, SOURCE_TYPE_TASK, task_id), str(issue.id))

        est = WorkloadEstimate.objects.get(issue=issue)
        self.assertEqual(
            _ledger_done(self.run, SOURCE_TYPE_TASK_ESTIMATE, task_id), str(est.id)
        )

    def test_parent_skip_ledger_row_does_not_overwrite_issue_ledger_row(self):
        from plane.clickup_migrate.writers import (
            SOURCE_TYPE_TASK,
            SOURCE_TYPE_TASK_ESTIMATE,
            _ledger_done,
            _record_upsert,
        )

        parent_issue = self._issue()
        self._issue(parent=parent_issue)  # countable child → parent_issue is a parent
        task_id = f"cu-collide-parent-{uuid.uuid4().hex[:8]}"

        _record_upsert(
            self.run, SOURCE_TYPE_TASK, task_id, "Issue", str(parent_issue.id),
            MigrationRecord.STATUS_CREATED,
        )

        token = write_workload_estimate(
            self.run, parent_issue, task_id, 7_200_000, False, self._user_cache(), dry_run=False,
        )
        self.assertEqual(token, "skipped-parent")

        # The parent-skip note must not clobber the Issue row either.
        self.assertEqual(_ledger_done(self.run, SOURCE_TYPE_TASK, task_id), str(parent_issue.id))
        skip_row = MigrationRecord.objects.get(
            run=self.run, source_type=SOURCE_TYPE_TASK_ESTIMATE, source_id=task_id
        )
        self.assertEqual(skip_row.status, MigrationRecord.STATUS_SKIPPED)
