# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Unit tests for the SP1 "last N days" window: the ClickUp date_updated_gt
# server-side filter and the out-of-window ancestor backfill. These run
# without a live database or ClickUp connection.

from django.test import SimpleTestCase

from plane.clickup_migrate.client import ClickUpClient
from plane.clickup_migrate.management.commands.migrate_clickup import Command


class _CapturingClient(ClickUpClient):
    """ClickUpClient whose _get records calls instead of hitting the API."""

    def __init__(self):
        super().__init__(token="pk_test", team_id="123")
        self.calls = []
        self._pages = {}  # path -> list of response dicts (one per page)

    def _get(self, path, params=None, _retry=3):
        self.calls.append((path, dict(params or {})))
        # Single empty page terminates iter_tasks immediately.
        return {"tasks": [], "last_page": True}


class TestIterTasksDateFilter(SimpleTestCase):
    def test_date_updated_gt_added_when_set(self):
        client = _CapturingClient()
        list(client.iter_tasks("L1", archived=False, date_updated_gt=1_700_000_000_000))
        self.assertTrue(client.calls)
        _, params = client.calls[0]
        self.assertEqual(params.get("date_updated_gt"), 1_700_000_000_000)

    def test_no_date_filter_when_none(self):
        client = _CapturingClient()
        list(client.iter_tasks("L1", archived=False, date_updated_gt=None))
        _, params = client.calls[0]
        self.assertNotIn("date_updated_gt", params)


class TestDedupeTasks(SimpleTestCase):
    def test_dedupe_preserves_first_seen_order(self):
        tasks = [{"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "c"}]
        out = Command._dedupe_tasks(tasks)
        self.assertEqual([t["id"] for t in out], ["a", "b", "c"])

    def test_dedupe_drops_empty_ids(self):
        tasks = [{"id": ""}, {"name": "no-id"}, {"id": "x"}]
        out = Command._dedupe_tasks(tasks)
        self.assertEqual([t["id"] for t in out], ["x"])


class TestReferencedTaskIds(SimpleTestCase):
    def test_collects_parent_deps_and_links(self):
        task = {
            "id": "t1",
            "parent": "p1",
            "top_level_parent": "top1",
            "dependencies": [{"task_id": "d1"}, {"task_id": "d2"}],
            "linked_tasks": [{"task_id": "l1"}, {"link_id": "l2"}],
        }
        ids = Command._referenced_task_ids(task)
        self.assertEqual(ids, {"p1", "top1", "d1", "d2", "l1", "l2"})

    def test_empty_when_no_references(self):
        self.assertEqual(Command._referenced_task_ids({"id": "solo"}), set())


class _BackfillClient:
    """Minimal fake exposing get_task from an in-memory task graph."""

    def __init__(self, graph):
        self.graph = graph
        self.fetched = []

    def get_task(self, task_id):
        self.fetched.append(task_id)
        return self.graph.get(task_id)  # None → deleted/inaccessible


class TestBackfillAncestors(SimpleTestCase):
    def test_transitive_closure(self):
        # In-window: A → parent B (out) → parent C (out). C has no parent.
        cmd = Command()
        in_window = [{"id": "A", "parent": "B"}]
        graph = {"B": {"id": "B", "parent": "C"}, "C": {"id": "C"}}
        complete, backfilled = cmd._backfill_ancestors(_BackfillClient(graph), in_window)
        ids = sorted(t["id"] for t in complete)
        self.assertEqual(ids, ["A", "B", "C"])
        self.assertEqual(backfilled, 2)

    def test_deleted_parent_is_skipped_not_looped(self):
        cmd = Command()
        in_window = [{"id": "A", "parent": "GHOST"}]
        client = _BackfillClient({})  # GHOST resolves to None (deleted)
        complete, backfilled = cmd._backfill_ancestors(client, in_window)
        self.assertEqual([t["id"] for t in complete], ["A"])
        self.assertEqual(backfilled, 0)
        # Fetched exactly once — the None result is cached, no infinite loop.
        self.assertEqual(client.fetched, ["GHOST"])

    def test_no_backfill_when_all_in_window(self):
        cmd = Command()
        in_window = [{"id": "A", "parent": "B"}, {"id": "B"}]
        client = _BackfillClient({})
        complete, backfilled = cmd._backfill_ancestors(client, in_window)
        self.assertEqual(backfilled, 0)
        self.assertEqual(client.fetched, [])
        self.assertEqual(sorted(t["id"] for t in complete), ["A", "B"])
