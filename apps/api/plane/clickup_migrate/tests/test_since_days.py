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


class TestHeuristicStatusGroup(SimpleTestCase):
    def test_common_status_names(self):
        m = Command._heuristic_status_group
        self.assertEqual(m("Open"), "unstarted")
        self.assertEqual(m("Closed"), "completed")
        self.assertEqual(m("done"), "completed")
        self.assertEqual(m("in progress"), "started")
        self.assertEqual(m("not started"), "unstarted")  # not the 'started' substring
        self.assertEqual(m("to do"), "unstarted")
        self.assertEqual(m("qa-review"), "started")
        self.assertEqual(m("code-review"), "started")
        self.assertEqual(m("backlog"), "backlog")
        self.assertEqual(m("pending"), "backlog")
        self.assertEqual(m("Cancelled"), "cancelled")

    def test_unknown_and_empty_return_none(self):
        self.assertIsNone(Command._heuristic_status_group("Zzxqwv"))
        self.assertIsNone(Command._heuristic_status_group(""))
        self.assertIsNone(Command._heuristic_status_group(None))


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


class _AttachmentClient:
    """Fake exposing get_task, recording which task ids were detail-fetched."""

    def __init__(self, detail_graph=None):
        self.detail_graph = detail_graph or {}
        self.fetched = []

    def get_task(self, task_id):
        self.fetched.append(task_id)
        return self.detail_graph.get(task_id)  # None → 404/deleted


class TestResolveAttachments(SimpleTestCase):
    """Issue #6: list-view tasks omit `attachments`; detail fetch fills the gap."""

    def _counts(self):
        return {"attachment_detail_fetch": 0}

    def test_disabled_returns_empty_and_never_fetches(self):
        client = _AttachmentClient({"T1": {"attachments": [{"id": "a1"}]}})
        counts = self._counts()
        out = Command._resolve_attachments(
            {"id": "T1"}, "T1", client, migrate_attachments=False, counts=counts
        )
        self.assertEqual(out, [])
        self.assertEqual(client.fetched, [])  # no wasted API call when off
        self.assertEqual(counts["attachment_detail_fetch"], 0)

    def test_list_view_task_triggers_detail_fetch(self):
        # List endpoint omits `attachments` entirely (the real bug).
        client = _AttachmentClient({"T1": {"attachments": [{"id": "a1"}, {"id": "a2"}]}})
        counts = self._counts()
        out = Command._resolve_attachments(
            {"id": "T1"}, "T1", client, migrate_attachments=True, counts=counts
        )
        self.assertEqual([a["id"] for a in out], ["a1", "a2"])
        self.assertEqual(client.fetched, ["T1"])  # one detail fetch
        self.assertEqual(counts["attachment_detail_fetch"], 1)

    def test_detail_none_yields_empty_without_crashing(self):
        # get_task 404 → None; must degrade to [] not raise.
        client = _AttachmentClient({})  # T1 not present → None
        counts = self._counts()
        out = Command._resolve_attachments(
            {"id": "T1"}, "T1", client, migrate_attachments=True, counts=counts
        )
        self.assertEqual(out, [])
        self.assertEqual(client.fetched, ["T1"])
        self.assertEqual(counts["attachment_detail_fetch"], 1)

    def test_task_with_no_attachments_returns_empty(self):
        # Detail fetched, task genuinely has zero attachments.
        client = _AttachmentClient({"T1": {"attachments": []}})
        counts = self._counts()
        out = Command._resolve_attachments(
            {"id": "T1"}, "T1", client, migrate_attachments=True, counts=counts
        )
        self.assertEqual(out, [])
        self.assertEqual(counts["attachment_detail_fetch"], 1)

    def test_preloaded_attachments_skip_detail_fetch(self):
        # If a task already carries `attachments` (e.g. a detail-fetched
        # ancestor), reuse it — no second round-trip.
        client = _AttachmentClient({})
        counts = self._counts()
        out = Command._resolve_attachments(
            {"id": "T1", "attachments": [{"id": "a1"}]}, "T1", client,
            migrate_attachments=True, counts=counts,
        )
        self.assertEqual([a["id"] for a in out], ["a1"])
        self.assertEqual(client.fetched, [])  # already had them
        self.assertEqual(counts["attachment_detail_fetch"], 0)


# ─────────────────────────────────────────────────────────────────────
# --apply pass-0: ancestors must reach the write path, not just --plan
# ─────────────────────────────────────────────────────────────────────

class _StructureClient(_BackfillClient):
    """_BackfillClient plus the space/folder/list surface _crawl_all_tasks walks."""

    def __init__(self, graph, tasks_by_list):
        super().__init__(graph)
        self.tasks_by_list = tasks_by_list
        self.windows = []

    def get_spaces(self):
        return [{"id": "S1"}]

    def get_folderless_lists(self, space_id):
        return [{"id": lid} for lid in self.tasks_by_list]

    def get_folders(self, space_id):
        return []

    def get_lists_in_folder(self, folder_id):
        return []

    def iter_tasks(self, list_id, archived=False, date_updated_gt=None):
        self.windows.append(date_updated_gt)
        if archived:
            return
        yield list(self.tasks_by_list.get(list_id, [])), 0


class TestApplyPassZeroClosesOverAncestors(SimpleTestCase):
    """Regression for the 2026-07-28 staging run.

    `--plan` had always closed over out-of-window parents, but `--apply` never
    did — despite --since-days' help text promising it — so 296 subtasks whose
    parent fell outside the 90-day window were logged "Orphan subtask" and
    landed at top level. `--apply` now runs the same backfill and feeds the
    closed-over set through the tasks-by-list channel, so this asserts the
    out-of-window parent actually reaches the write path.
    """

    def test_out_of_window_parent_is_grouped_under_its_own_list(self):
        from plane.clickup_migrate import snapshot as snap

        cmd = Command()
        # A is in-window in L1; its parent B was last touched long ago and
        # lives in L2, so the windowed crawl never returns it.
        client = _StructureClient(
            graph={"B": {"id": "B", "list": {"id": "L2"}}},
            tasks_by_list={"L1": [{"id": "A", "parent": "B", "list": {"id": "L1"}}], "L2": []},
        )

        windowed = cmd._crawl_all_tasks(client, ["S1"], date_updated_gt=12345)
        complete, backfilled = cmd._backfill_ancestors(client, windowed)
        grouped = snap.group_by_list(complete)

        self.assertEqual([t["id"] for t in windowed], ["A"])
        self.assertEqual(backfilled, 1)
        # The parent must be present AND addressable by its own list, or the
        # traversal would never write it and the link would orphan again.
        self.assertIn("L2", grouped)
        self.assertEqual([t["id"] for t in grouped["L2"]], ["B"])
        self.assertEqual([t["id"] for t in grouped["L1"]], ["A"])

    def test_crawl_propagates_the_window_to_every_list(self):
        cmd = Command()
        client = _StructureClient(graph={}, tasks_by_list={"L1": [], "L2": []})
        cmd._crawl_all_tasks(client, ["S1"], date_updated_gt=999)
        # Every page request must carry the bound — a dropped filter would
        # silently turn a windowed run into a full-history pull.
        self.assertTrue(client.windows)
        self.assertEqual(set(client.windows), {999})
