# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Unit tests for writers.py — idempotency key construction, relation
# canonicalization, gate logic, and ledger resume.
# Also DB-backed load-bearing tests (H3) asserting:
#   (a) created_by_id is non-NULL after write_issue (C1 regression guard)
#   (b) blocking relation canonical direction is swapped correctly
#   (c) writing the same entity twice produces exactly 1 row (idempotency)

import json
import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from plane.clickup_migrate.normalize import make_status_key
from plane.clickup_migrate.writers import (
    EXTERNAL_SOURCE,
    MappingCache,
    _ledger_done,
    check_apply_gate,
    write_issue_relation,
)


# ─────────────────────────────────────────────────────────────────────
# Helpers shared by H3 tests
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
    from plane.clickup_migrate.models import MigrationRun
    return MigrationRun.objects.create(status="pending")


class TestExternalSourceConstant(SimpleTestCase):
    def test_constant_value(self):
        self.assertEqual(EXTERNAL_SOURCE, "clickup")


class TestMakingStatusKey(SimpleTestCase):
    """Verify the composite key format used by MappingCache."""

    def test_status_cache_key_format(self):
        key = make_status_key("list-abc", "In Progress")
        parsed = json.loads(key)
        self.assertEqual(parsed[0], "list-abc")
        self.assertEqual(parsed[1], "In Progress")


class TestIssueRelationCanonicalisation(SimpleTestCase):
    """Verify the relation direction logic without hitting the DB."""

    def test_get_actual_relation_blocking_returns_blocked_by(self):
        from plane.utils.issue_relation_mapper import get_actual_relation

        # 'blocking' canonicalises to 'blocked_by'
        self.assertEqual(get_actual_relation("blocking"), "blocked_by")

    def test_get_actual_relation_blocked_by_stays(self):
        from plane.utils.issue_relation_mapper import get_actual_relation

        self.assertEqual(get_actual_relation("blocked_by"), "blocked_by")

    def test_get_actual_relation_relates_to_symmetric(self):
        from plane.utils.issue_relation_mapper import get_actual_relation

        self.assertEqual(get_actual_relation("relates_to"), "relates_to")

    def test_get_actual_relation_start_after(self):
        from plane.utils.issue_relation_mapper import get_actual_relation

        self.assertEqual(get_actual_relation("start_after"), "start_before")

    def test_get_actual_relation_finish_after(self):
        from plane.utils.issue_relation_mapper import get_actual_relation

        self.assertEqual(get_actual_relation("finish_after"), "finish_before")


class TestCheckApplyGate(TestCase):
    """Gate logic: refuse --apply if any row is unapproved or unsigned."""

    def _make_run(self):
        from plane.clickup_migrate.models import MigrationRun
        return MigrationRun.objects.create(status="pending")

    def test_empty_run_passes_gate(self):
        run = self._make_run()
        blockers = check_apply_gate(run)
        self.assertEqual(blockers, [])

    def test_unapproved_mapping_blocks(self):
        from plane.clickup_migrate.models import MappingTable
        run = self._make_run()
        MappingTable.objects.create(
            run=run,
            kind=MappingTable.KIND_STATUS,
            source_key='["list-1","todo"]',
            target_value="backlog",
            approved=False,
        )
        blockers = check_apply_gate(run)
        self.assertTrue(len(blockers) > 0)
        self.assertIn("MappingTable", blockers[0])

    def test_unsigned_email_coverage_blocks(self):
        from plane.clickup_migrate.models import EmailCoverage
        run = self._make_run()
        EmailCoverage.objects.create(
            run=run,
            clickup_email="user@example.com",
            signed_off=False,
        )
        blockers = check_apply_gate(run)
        self.assertTrue(len(blockers) > 0)
        self.assertIn("EmailCoverage", blockers[0])

    def test_all_approved_passes(self):
        from plane.clickup_migrate.models import MappingTable, EmailCoverage
        run = self._make_run()
        MappingTable.objects.create(
            run=run,
            kind=MappingTable.KIND_STATUS,
            source_key='["list-1","todo"]',
            target_value="backlog",
            approved=True,
        )
        EmailCoverage.objects.create(
            run=run,
            clickup_email="user@example.com",
            signed_off=True,
        )
        blockers = check_apply_gate(run)
        self.assertEqual(blockers, [])


class TestLedgerResume(TestCase):
    """Ledger-based resume: _ledger_done returns plane_id or None."""

    def _make_run(self):
        from plane.clickup_migrate.models import MigrationRun
        return MigrationRun.objects.create(status="pending")

    def test_returns_none_when_no_record(self):
        run = self._make_run()
        result = _ledger_done(run, "task", "cu-task-999")
        self.assertIsNone(result)

    def test_returns_plane_id_when_created(self):
        from plane.clickup_migrate.models import MigrationRecord
        run = self._make_run()
        MigrationRecord.objects.create(
            run=run,
            source_type="task",
            source_id="cu-task-001",
            plane_type="Issue",
            plane_id="plane-uuid-abc",
            status=MigrationRecord.STATUS_CREATED,
        )
        result = _ledger_done(run, "task", "cu-task-001")
        self.assertEqual(result, "plane-uuid-abc")

    def test_returns_none_for_error_status(self):
        from plane.clickup_migrate.models import MigrationRecord
        run = self._make_run()
        MigrationRecord.objects.create(
            run=run,
            source_type="task",
            source_id="cu-task-002",
            plane_type="Issue",
            plane_id="",
            status=MigrationRecord.STATUS_ERROR,
            error="S3 upload failed",
        )
        result = _ledger_done(run, "task", "cu-task-002")
        self.assertIsNone(result)


class TestMappingCache(TestCase):
    """MappingCache resolves approved rows; no Anthropic calls in apply phase."""

    def _make_run(self):
        from plane.clickup_migrate.models import MigrationRun
        return MigrationRun.objects.create(status="pending")

    def test_status_group_from_approved_row(self):
        import json
        from plane.clickup_migrate.models import MappingTable
        run = self._make_run()
        key = make_status_key("list-1", "Doing")
        MappingTable.objects.create(
            run=run,
            kind=MappingTable.KIND_STATUS,
            source_key=key,
            target_value="started",
            approved=True,
        )
        cache = MappingCache(run)
        self.assertEqual(cache.status_group("list-1", "Doing"), "started")

    def test_status_group_defaults_to_backlog_when_not_found(self):
        run = self._make_run()
        cache = MappingCache(run)
        self.assertEqual(cache.status_group("list-x", "Unknown"), "backlog")

    def test_priority_mapping(self):
        import json
        from plane.clickup_migrate.models import MappingTable
        run = self._make_run()
        MappingTable.objects.create(
            run=run,
            kind=MappingTable.KIND_PRIORITY,
            source_key=json.dumps("urgent"),
            target_value="urgent",
            approved=True,
        )
        cache = MappingCache(run)
        self.assertEqual(cache.priority("urgent"), "urgent")

    def test_unapproved_row_ignored(self):
        import json
        from plane.clickup_migrate.models import MappingTable
        run = self._make_run()
        key = make_status_key("list-2", "Review")
        MappingTable.objects.create(
            run=run,
            kind=MappingTable.KIND_STATUS,
            source_key=key,
            target_value="started",
            approved=False,  # unapproved — should be ignored
        )
        cache = MappingCache(run)
        # Falls back to default because row is not approved.
        self.assertEqual(cache.status_group("list-2", "Review"), "backlog")


# ─────────────────────────────────────────────────────────────────────
# H3(a) — Authorship non-NULL after write_issue  (C1 regression guard)
# ─────────────────────────────────────────────────────────────────────

class TestWriteIssueAuthorship(TestCase):
    """H3(a): write_issue must set created_by_id to the resolved author,
    not NULL.  This is a regression guard for C1 (BaseModel.save() clobbers
    created_by via crum in management commands unless disable_auto_set_user=True
    is passed as a save kwarg).
    """

    def setUp(self):
        self.bot_user = _make_user(is_bot=True)
        self.real_user = _make_user()
        self.workspace = _make_workspace(self.bot_user)
        self.project = _make_project(self.workspace, self.bot_user)
        self.state = _make_state(self.project, self.workspace, self.bot_user)
        self.run = _make_run()

    def _make_mapping_cache(self):
        from plane.clickup_migrate.writers import MappingCache
        return MappingCache(self.run)

    def _make_user_cache(self):
        from plane.clickup_migrate.writers import UserCache
        return UserCache(self.bot_user)

    def test_created_by_is_non_null_with_known_email(self):
        """Issue created from a task whose creator email matches a Plane user
        must have created_by_id equal to that user's id."""
        from plane.clickup_migrate.writers import write_issue
        from plane.db.models import Issue

        task = {
            "id": f"cu-task-{uuid.uuid4().hex[:8]}",
            "name": "Test issue authorship",
            "priority": None,
            "description": "",
            "markdown_description": "",
            "date_created": None,
            "date_updated": None,
            "creator": {"email": self.real_user.email},
        }
        user_cache = self._make_user_cache()
        mapping_cache = self._make_mapping_cache()

        issue = write_issue(
            self.run, self.project, self.workspace,
            task, self.state, mapping_cache, user_cache, dry_run=False,
        )

        self.assertIsNotNone(issue, "write_issue returned None unexpectedly")
        # Reload from DB — do NOT trust the in-memory object whose save()
        # may have been intercepted.
        db_issue = Issue.all_objects.get(pk=issue.pk)
        self.assertIsNotNone(
            db_issue.created_by_id,
            "created_by_id must not be NULL after write_issue (C1 regression)",
        )
        self.assertEqual(
            db_issue.created_by_id,
            self.real_user.id,
            "created_by_id must equal the resolved Plane user, not the bot or NULL",
        )

    def test_created_by_falls_back_to_bot_for_unknown_email(self):
        """Unknown creator email → bot fallback, still non-NULL."""
        from plane.clickup_migrate.writers import write_issue
        from plane.db.models import Issue

        task = {
            "id": f"cu-task-{uuid.uuid4().hex[:8]}",
            "name": "Unknown creator",
            "priority": None,
            "description": "",
            "markdown_description": "",
            "date_created": None,
            "date_updated": None,
            "creator": {"email": "ghost-nobody@unknown.invalid"},
        }
        user_cache = self._make_user_cache()
        mapping_cache = self._make_mapping_cache()

        issue = write_issue(
            self.run, self.project, self.workspace,
            task, self.state, mapping_cache, user_cache, dry_run=False,
        )

        self.assertIsNotNone(issue)
        db_issue = Issue.all_objects.get(pk=issue.pk)
        self.assertIsNotNone(db_issue.created_by_id)
        self.assertEqual(db_issue.created_by_id, self.bot_user.id)


# ─────────────────────────────────────────────────────────────────────
# H3(b) — blocking relation is stored with swapped canonical direction
# ─────────────────────────────────────────────────────────────────────

class TestWriteIssueRelationDirection(TestCase):
    """H3(b): a ClickUp 'blocking' relation (A blocks B) must be stored as
    (issue=B, related_issue=A, relation_type=blocked_by) — the Plane canonical
    direction. This validates both get_actual_relation canonicalization AND the
    ID-swap logic in write_issue_relation.
    """

    def setUp(self):
        self.bot_user = _make_user(is_bot=True)
        self.workspace = _make_workspace(self.bot_user)
        self.project = _make_project(self.workspace, self.bot_user)
        self.state = _make_state(self.project, self.workspace, self.bot_user)
        self.run = _make_run()

    def _create_issue_in_ledger(self, clickup_task_id: str):
        """Write a minimal issue and register it in the MigrationRecord ledger."""
        from plane.clickup_migrate.writers import write_issue, UserCache, MappingCache

        task = {
            "id": clickup_task_id,
            "name": f"Issue for {clickup_task_id}",
            "priority": None,
            "description": "",
            "markdown_description": "",
            "date_created": None,
            "date_updated": None,
            "creator": None,
        }
        user_cache = UserCache(self.bot_user)
        mapping_cache = MappingCache(self.run)

        issue = write_issue(
            self.run, self.project, self.workspace,
            task, self.state, mapping_cache, user_cache, dry_run=False,
        )
        self.assertIsNotNone(issue, f"Failed to create issue for task {clickup_task_id}")
        return issue

    def test_blocking_relation_swaps_issue_and_related(self):
        """ClickUp: A (blocker) blocking B (blocked).
        Plane must store: issue=B, related_issue=A, type=blocked_by.
        """
        from plane.clickup_migrate.writers import write_issue_relation
        from plane.db.models import IssueRelation

        source_id = f"cu-src-{uuid.uuid4().hex[:8]}"  # A = blocker
        target_id = f"cu-tgt-{uuid.uuid4().hex[:8]}"  # B = blocked

        source_issue = self._create_issue_in_ledger(source_id)
        target_issue = self._create_issue_in_ledger(target_id)

        ok = write_issue_relation(
            self.run,
            "blocking",
            source_id,    # A = the one doing the blocking
            target_id,    # B = the one being blocked
            self.workspace,
            self.bot_user,
            dry_run=False,
        )
        self.assertTrue(ok, "write_issue_relation returned False")

        # The stored row: B is blocked_by A.
        relation = IssueRelation.objects.get(
            issue_id=target_issue.pk,      # B
            related_issue_id=source_issue.pk,  # A
        )
        self.assertEqual(relation.relation_type, "blocked_by")

    def test_waiting_on_relation_not_swapped(self):
        """ClickUp: A waiting_on B → Plane: issue=A, related_issue=B, type=blocked_by.
        No ID swap for waiting_on (only 'blocking' swaps).
        """
        from plane.clickup_migrate.writers import write_issue_relation
        from plane.db.models import IssueRelation

        source_id = f"cu-w-src-{uuid.uuid4().hex[:8]}"
        target_id = f"cu-w-tgt-{uuid.uuid4().hex[:8]}"

        source_issue = self._create_issue_in_ledger(source_id)
        target_issue = self._create_issue_in_ledger(target_id)

        ok = write_issue_relation(
            self.run,
            "waiting_on",
            source_id,
            target_id,
            self.workspace,
            self.bot_user,
            dry_run=False,
        )
        self.assertTrue(ok)

        relation = IssueRelation.objects.get(
            issue_id=source_issue.pk,
            related_issue_id=target_issue.pk,
        )
        self.assertEqual(relation.relation_type, "blocked_by")


# ─────────────────────────────────────────────────────────────────────
# H3(c) — Idempotency: writing the same entity twice creates 0 new rows
# ─────────────────────────────────────────────────────────────────────

class TestWriterIdempotency(TestCase):
    """H3(c): calling the same writer twice with identical external_id must
    produce exactly 1 Issue row and 1 MigrationRecord row (not 2).
    """

    def setUp(self):
        self.bot_user = _make_user(is_bot=True)
        self.workspace = _make_workspace(self.bot_user)
        self.project = _make_project(self.workspace, self.bot_user)
        self.state = _make_state(self.project, self.workspace, self.bot_user)
        self.run = _make_run()

    def test_write_issue_twice_creates_one_row(self):
        from plane.clickup_migrate.writers import write_issue, UserCache, MappingCache
        from plane.clickup_migrate.models import MigrationRecord
        from plane.db.models import Issue

        task_id = f"cu-idem-{uuid.uuid4().hex[:8]}"
        task = {
            "id": task_id,
            "name": "Idempotency test task",
            "priority": None,
            "description": "",
            "markdown_description": "",
            "date_created": None,
            "date_updated": None,
            "creator": None,
        }
        user_cache = UserCache(self.bot_user)
        mapping_cache = MappingCache(self.run)

        # First write.
        issue1 = write_issue(
            self.run, self.project, self.workspace,
            task, self.state, mapping_cache, user_cache, dry_run=False,
        )
        self.assertIsNotNone(issue1)

        issue_count_after_1 = Issue.all_objects.filter(
            external_source=EXTERNAL_SOURCE, external_id=task_id
        ).count()
        record_count_after_1 = MigrationRecord.objects.filter(
            run=self.run, source_type="task", source_id=task_id
        ).count()

        # Second write — must be a no-op.
        issue2 = write_issue(
            self.run, self.project, self.workspace,
            task, self.state, mapping_cache, user_cache, dry_run=False,
        )
        # issue2 may be None (ledger skip) or the same object — both are valid.

        issue_count_after_2 = Issue.all_objects.filter(
            external_source=EXTERNAL_SOURCE, external_id=task_id
        ).count()
        record_count_after_2 = MigrationRecord.objects.filter(
            run=self.run, source_type="task", source_id=task_id
        ).count()

        self.assertEqual(issue_count_after_1, 1, "Should have exactly 1 Issue row after first write")
        self.assertEqual(issue_count_after_2, 1, "Second write must not create a duplicate Issue row")
        self.assertEqual(record_count_after_1, 1, "Should have exactly 1 MigrationRecord after first write")
        self.assertEqual(record_count_after_2, 1, "Second write must not create a duplicate MigrationRecord")
