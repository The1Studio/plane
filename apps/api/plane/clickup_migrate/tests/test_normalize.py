# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Unit tests for normalize.py — status enum validation, key construction,
# and value collection logic.

import json

from django.test import SimpleTestCase

from plane.clickup_migrate.normalize import (
    VALID_STATE_GROUPS,
    collect_distinct_statuses,
    collect_distinct_custom_field_defs,
    make_status_key,
    validate_state_group,
)


class TestMakeStatusKey(SimpleTestCase):
    def test_produces_json_array(self):
        key = make_status_key("list-123", "In Progress")
        parsed = json.loads(key)
        self.assertEqual(parsed, ["list-123", "In Progress"])

    def test_different_lists_same_name_produce_different_keys(self):
        k1 = make_status_key("list-a", "Done")
        k2 = make_status_key("list-b", "Done")
        self.assertNotEqual(k1, k2)


class TestValidateStateGroup(SimpleTestCase):
    def test_valid_groups_accepted(self):
        for group in VALID_STATE_GROUPS:
            self.assertEqual(validate_state_group(group), group)

    def test_case_insensitive(self):
        self.assertEqual(validate_state_group("BACKLOG"), "backlog")
        self.assertEqual(validate_state_group("Completed"), "completed")

    def test_triage_rejected(self):
        # 'triage' is NOT in VALID_STATE_GROUPS — must never be an output
        self.assertIsNone(validate_state_group("triage"))

    def test_unknown_group_rejected(self):
        self.assertIsNone(validate_state_group("doing"))
        self.assertIsNone(validate_state_group("open"))
        self.assertIsNone(validate_state_group("closed"))

    def test_whitespace_stripped(self):
        self.assertEqual(validate_state_group("  backlog  "), "backlog")


class TestCollectDistinctStatuses(SimpleTestCase):
    def _make_task(self, list_id, list_name, status, color="#fff"):
        return {
            "list": {"id": list_id, "name": list_name},
            "status": {"status": status, "color": color},
        }

    def test_deduplicates_by_list_and_status(self):
        tasks = [
            self._make_task("list-1", "Sprint 1", "todo"),
            self._make_task("list-1", "Sprint 1", "todo"),
            self._make_task("list-1", "Sprint 1", "done"),
        ]
        distinct = collect_distinct_statuses(tasks)
        self.assertEqual(len(distinct), 2)

    def test_same_name_different_list_are_distinct(self):
        tasks = [
            self._make_task("list-a", "A", "todo"),
            self._make_task("list-b", "B", "todo"),
        ]
        distinct = collect_distinct_statuses(tasks)
        self.assertEqual(len(distinct), 2)

    def test_count_is_accurate(self):
        tasks = [self._make_task("list-1", "S", "todo")] * 5
        distinct = collect_distinct_statuses(tasks)
        self.assertEqual(distinct[0]["count"], 5)

    def test_empty_tasks(self):
        self.assertEqual(collect_distinct_statuses([]), [])


class TestCollectDistinctCustomFieldDefs(SimpleTestCase):
    def test_deduplicates_by_field_id(self):
        defs = {
            "list-1": [{"id": "f1", "name": "Priority", "type": "drop_down", "type_config": {}}],
            "list-2": [{"id": "f1", "name": "Priority", "type": "drop_down", "type_config": {}}],
        }
        distinct = collect_distinct_custom_field_defs(defs)
        self.assertEqual(len(distinct), 1)
        self.assertEqual(distinct[0]["field_id"], "f1")

    def test_different_field_ids_both_included(self):
        defs = {
            "list-1": [
                {"id": "f1", "name": "A", "type": "text", "type_config": {}},
                {"id": "f2", "name": "B", "type": "number", "type_config": {}},
            ],
        }
        distinct = collect_distinct_custom_field_defs(defs)
        self.assertEqual(len(distinct), 2)

    def test_empty_defs(self):
        self.assertEqual(collect_distinct_custom_field_defs({}), [])
