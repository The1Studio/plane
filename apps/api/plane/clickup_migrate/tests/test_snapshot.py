# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Unit tests for the portable raw-extract snapshot (`clickup_migrate/snapshot.py`).
#
# No DB and no ClickUp connection — the module is deliberately pure file I/O so
# the extract/load decoupling can be tested without either.

import json
import os
import tempfile
import unittest

from django.test import SimpleTestCase

from plane.clickup_migrate import snapshot as snap


def _task(tid, updated, list_id="L1", name=None):
    return {
        "id": tid,
        "name": name or f"task {tid}",
        "date_updated": str(updated),
        "list": {"id": list_id, "name": f"list {list_id}"},
    }


class TestWatermark(SimpleTestCase):
    def test_watermark_is_max_date_updated(self):
        tasks = [_task("a", 100), _task("b", 300), _task("c", 200)]
        self.assertEqual(snap.compute_watermark(tasks), 300)

    def test_watermark_none_when_no_usable_timestamps(self):
        # None must NOT collapse to 0 — a 0 bound would look like a delta that
        # matched every task ever, silently turning a delta into a full pull.
        self.assertIsNone(snap.compute_watermark([{"id": "a"}]))
        self.assertIsNone(snap.compute_watermark([]))

    def test_watermark_ignores_unparseable_values(self):
        tasks = [_task("a", 100), {"id": "b", "date_updated": "not-a-number"}]
        self.assertEqual(snap.compute_watermark(tasks), 100)


class TestRoundTrip(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "snap.jsonl")

    def test_write_then_read_preserves_tasks_and_manifest(self):
        tasks = [_task("a", 100), _task("b", 300)]
        manifest = snap.write(self.path, tasks, space_ids=["S1"], since_days=90)

        self.assertEqual(manifest["task_count"], 2)
        self.assertEqual(manifest["watermark"], 300)

        loaded, read_manifest = snap.read(self.path)
        self.assertEqual(set(loaded), {"a", "b"})
        self.assertEqual(loaded["a"]["name"], "task a")
        self.assertEqual(read_manifest["watermark"], 300)
        self.assertEqual(read_manifest["space_ids"], ["S1"])
        self.assertEqual(read_manifest["since_days"], 90)

    def test_payload_is_preserved_verbatim(self):
        # The writers consume raw ClickUp shapes, so a snapshot must not
        # normalise anything — otherwise it silently drifts from the live API.
        raw = {
            "id": "a", "date_updated": "100", "list": {"id": "L1"},
            "custom_fields": [{"id": "cf", "value": {"nested": [1, 2]}}],
            "unicode": "tiếng việt — em dash",
            "null_field": None,
        }
        snap.write(self.path, [raw])
        loaded, _ = snap.read(self.path)
        self.assertEqual(loaded["a"], raw)

    def test_first_line_is_the_manifest(self):
        snap.write(self.path, [_task("a", 100)])
        with open(self.path, encoding="utf-8") as fh:
            first = json.loads(fh.readline())
        self.assertTrue(first.get("_manifest"))

    def test_empty_task_set_round_trips(self):
        manifest = snap.write(self.path, [])
        self.assertEqual(manifest["task_count"], 0)
        self.assertIsNone(manifest["watermark"])
        loaded, _ = snap.read(self.path)
        self.assertEqual(loaded, {})


class TestReadRejectsMalformed(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "snap.jsonl")

    def _write_raw(self, text):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_missing_manifest_raises(self):
        self._write_raw(json.dumps({"id": "a"}) + "\n")
        with self.assertRaises(ValueError):
            snap.read(self.path)

    def test_unknown_version_raises(self):
        self._write_raw(json.dumps({"_manifest": 1, "version": 999}) + "\n")
        with self.assertRaises(ValueError):
            snap.read(self.path)

    def test_empty_file_raises(self):
        self._write_raw("")
        with self.assertRaises(ValueError):
            snap.read(self.path)


class TestAtomicWrite(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "snap.jsonl")

    def test_failed_write_leaves_previous_snapshot_intact_and_no_debris(self):
        snap.write(self.path, [_task("a", 100)])

        class Boom(Exception):
            pass

        class ExplodingList(list):
            def __iter__(self):
                yield _task("b", 200)
                raise Boom("simulated failure mid-write")

        with self.assertRaises(Boom):
            snap.write(self.path, ExplodingList())

        # Old snapshot still readable — a half-written file would be worse than
        # no file, because a later run would load it as a complete extract.
        loaded, _ = snap.read(self.path)
        self.assertEqual(set(loaded), {"a"})
        leftovers = [f for f in os.listdir(self.dir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class TestMerge(SimpleTestCase):
    def test_delta_wins_and_counts_are_reported(self):
        base = {"a": _task("a", 100), "b": _task("b", 100)}
        delta = [_task("b", 500, name="b updated"), _task("c", 600)]

        merged, updated, added = snap.merge(base, delta)

        self.assertEqual(updated, 1)
        self.assertEqual(added, 1)
        self.assertEqual(set(merged), {"a", "b", "c"})
        self.assertEqual(merged["b"]["name"], "b updated")
        self.assertEqual(merged["a"]["name"], "task a")

    def test_merge_does_not_mutate_base(self):
        base = {"a": _task("a", 100)}
        snap.merge(base, [_task("a", 500, name="changed")])
        self.assertEqual(base["a"]["name"], "task a")

    def test_merged_watermark_advances(self):
        base = {"a": _task("a", 100)}
        merged, _, _ = snap.merge(base, [_task("b", 900)])
        self.assertEqual(snap.compute_watermark(merged.values()), 900)

    def test_tasks_without_id_are_skipped(self):
        merged, updated, added = snap.merge({}, [{"name": "no id"}])
        self.assertEqual((updated, added), (0, 0))
        self.assertEqual(merged, {})


class TestGroupByList(SimpleTestCase):
    def test_groups_tasks_by_list_id(self):
        tasks = [_task("a", 1, "L1"), _task("b", 2, "L2"), _task("c", 3, "L1")]
        grouped = snap.group_by_list(tasks)
        self.assertEqual(set(grouped), {"L1", "L2"})
        self.assertEqual({t["id"] for t in grouped["L1"]}, {"a", "c"})

    def test_tasks_without_list_are_dropped(self):
        # They cannot be placed in a Project, so replay must not invent one.
        grouped = snap.group_by_list([{"id": "a"}, _task("b", 1, "L1")])
        self.assertEqual(set(grouped), {"L1"})


class TestIncrementalScenario(SimpleTestCase):
    """The end-to-end shape the feature exists for: extract once, delta later."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "snap.jsonl")

    def test_seed_then_delta_then_replay(self):
        # Run 1 — seed from a full crawl.
        snap.write(self.path, [_task("a", 100), _task("b", 200)], space_ids=["S1"], since_days=90)
        loaded, manifest = snap.read(self.path)
        self.assertEqual(manifest["watermark"], 200)

        # Run 2 — only tasks updated after the watermark come back.
        delta = [_task("b", 700, name="b changed"), _task("c", 800)]
        merged, updated, added = snap.merge(loaded, delta)
        snap.write(self.path, merged.values(), space_ids=["S1"], since_days=90)

        # Import sees the union: untouched 'a', updated 'b', new 'c'.
        replay, manifest2 = snap.read(self.path)
        self.assertEqual(set(replay), {"a", "b", "c"})
        self.assertEqual(replay["b"]["name"], "b changed")
        self.assertEqual((updated, added), (1, 1))

        # Watermark advanced, so a third run's delta starts from the new high.
        self.assertEqual(manifest2["watermark"], 800)


if __name__ == "__main__":
    unittest.main()
