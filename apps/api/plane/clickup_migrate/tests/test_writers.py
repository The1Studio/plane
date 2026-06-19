# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Unit tests for writers.py — idempotency key construction, relation
# canonicalization, gate logic, and ledger resume.
# These tests mock the DB layer where needed and avoid live connections.

import json
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
