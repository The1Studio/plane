# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# DB integration tests (real Postgres) for cascade_ext's BFS descendant
# collection and the apply transaction. Mirrors the workload test style
# (TransactionTestCase + explicit ORM rows, real Postgres, no mocking the
# unit under test — except where the test IS about the dispatched
# notification kwarg, where mocking is the only way to observe it).
#
# Test matrix: plans/260822-cascade-complete-sub-items/phase-1-cascade-backend.md

import uuid
from unittest import mock

from django.test import TransactionTestCase

# Run Celery tasks inline (no broker in tests) for any test that does NOT
# explicitly mock issue_activity/model_activity itself.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.cascade_ext.service import (
    MAX_DEPTH,
    apply_cascade,
    collect_descendants,
    resolve_target_group,
)
from plane.db.models import Issue


# ---------------------------------------------------------------------------
# Shared helpers (mirror workload/tests/test_rollup.py)
# ---------------------------------------------------------------------------

def _ws(slug=None):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    owner = _user()
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner)


def _user(email=None, is_bot=False):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    email = email or f"u-{uid}@test.invalid"
    return User.objects.create_user(
        username=f"user_{uid}", email=email, password="x", is_bot=is_bot
    )


def _project(ws):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
    )


def _pmember(ws, proj, user, role=15, is_active=True):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(
        workspace=ws, project=proj, member=user, role=role, is_active=is_active
    )


def _state(ws, proj, group="started", name=None):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws,
        project=proj,
        name=name or f"{group}-{uuid.uuid4().hex[:4]}",
        color="#fff",
        group=group,
    )


def _issue(ws, proj, created_by, state=None, parent=None):
    return Issue.objects.create(
        workspace=ws,
        project=proj,
        name=f"i-{uuid.uuid4().hex[:6]}",
        created_by=created_by,
        state=state,
        parent=parent,
        sequence_id=1,
    )


# ---------------------------------------------------------------------------
# resolve_target_group — pure decision logic, still exercised against real
# State rows so `.group` reflects the same StateGroup choices as production.
# ---------------------------------------------------------------------------

class TestResolveTargetGroup(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        return ws, proj

    def test_unstarted_to_completed(self):
        ws, proj = self._setup()
        old = _state(ws, proj, "unstarted")
        new = _state(ws, proj, "completed")
        self.assertEqual(resolve_target_group(old, new), "completed")

    def test_completed_to_completed_is_noop(self):
        ws, proj = self._setup()
        old = _state(ws, proj, "completed")
        new = _state(ws, proj, "completed")
        self.assertIsNone(resolve_target_group(old, new))

    def test_completed_to_started_is_not_a_cascade(self):
        ws, proj = self._setup()
        old = _state(ws, proj, "completed")
        new = _state(ws, proj, "started")
        self.assertIsNone(resolve_target_group(old, new))

    def test_completed_to_cancelled_cascades(self):
        ws, proj = self._setup()
        old = _state(ws, proj, "completed")
        new = _state(ws, proj, "cancelled")
        self.assertEqual(resolve_target_group(old, new), "cancelled")

    def test_no_prior_state(self):
        ws, proj = self._setup()
        new = _state(ws, proj, "completed")
        self.assertEqual(resolve_target_group(None, new), "completed")


# ---------------------------------------------------------------------------
# collect_descendants — BFS + eligibility
# ---------------------------------------------------------------------------

class TestCollectDescendants(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        return ws, proj, user

    def test_leaf_has_no_descendants(self):
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        leaf = _issue(ws, proj, user, state=st)

        result = collect_descendants(root_issue=leaf, target_group="completed", actor_id=user.id)

        self.assertEqual(result["descendants"], [])
        self.assertFalse(result["depth_capped"])

    def test_three_level_tree_every_level_listed_with_project_completed_state(self):
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed", name="Done")
        root = _issue(ws, proj, user, state=st_started)
        mid = _issue(ws, proj, user, state=st_started, parent=root)
        leaf = _issue(ws, proj, user, state=st_started, parent=mid)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        by_id = {d["id"]: d for d in result["descendants"]}

        self.assertEqual(set(by_id.keys()), {str(mid.id), str(leaf.id)})
        self.assertEqual(by_id[str(mid.id)]["depth"], 1)
        self.assertEqual(by_id[str(leaf.id)]["depth"], 2)
        for node in by_id.values():
            self.assertTrue(node["eligible"])
            self.assertEqual(node["target_state_id"], str(st_completed.id))

    def test_same_tree_target_cancelled_resolves_cancelled_state(self):
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_cancelled = _state(ws, proj, "cancelled")
        root = _issue(ws, proj, user, state=st_started)
        _issue(ws, proj, user, state=st_started, parent=root)

        result = collect_descendants(root_issue=root, target_group="cancelled", actor_id=user.id)

        self.assertEqual(result["descendants"][0]["target_state_id"], str(st_cancelled.id))

    def test_cancelled_child_excluded_and_prunes_its_subtree(self):
        # INVERTED 2026-08-28 by plans/260828-module-cascade-terminal-status
        # Phase 0: a terminal node now PRUNES its subtree — the grandchild is
        # NOT listed. This is a deliberate, user-directed reversal of the
        # shipped rule (260822 Decision 5, "still traversed through"); do not
        # "fix" it back. A live sub-item under a cancelled parent is now left
        # live where it used to be swept.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_cancelled = _state(ws, proj, "cancelled")
        _state(ws, proj, "completed")
        root = _issue(ws, proj, user, state=st_started)
        cancelled_child = _issue(ws, proj, user, state=st_cancelled, parent=root)
        grandchild = _issue(ws, proj, user, state=st_started, parent=cancelled_child)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        ids = {d["id"] for d in result["descendants"]}

        self.assertNotIn(str(cancelled_child.id), ids)
        self.assertNotIn(str(grandchild.id), ids)
        self.assertIn(str(cancelled_child.id), result["traversed_ids"])

    def test_completed_child_excluded_mirrored_for_cancel_target_and_prunes_its_subtree(self):
        # INVERTED 2026-08-28 by plans/260828-module-cascade-terminal-status
        # Phase 0 — see the cancelled-child mirror above for the full note.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        _state(ws, proj, "cancelled")
        root = _issue(ws, proj, user, state=st_started)
        completed_child = _issue(ws, proj, user, state=st_completed, parent=root)
        grandchild = _issue(ws, proj, user, state=st_started, parent=completed_child)

        result = collect_descendants(root_issue=root, target_group="cancelled", actor_id=user.id)
        ids = {d["id"] for d in result["descendants"]}

        self.assertNotIn(str(completed_child.id), ids)
        self.assertNotIn(str(grandchild.id), ids)

    # Phase 0 (plans/260828-module-cascade-terminal-status, 2026-08-28) —
    # prune-at-terminal coverage beyond the two inversions above.

    def test_terminal_node_prunes_a_two_level_live_subtree(self):
        # Case A: nothing beneath a terminal node is listed OR visited.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        root = _issue(ws, proj, user, state=st_started)
        terminal_child = _issue(ws, proj, user, state=st_completed, parent=root)
        grandchild = _issue(ws, proj, user, state=st_started, parent=terminal_child)
        great_grandchild = _issue(ws, proj, user, state=st_started, parent=grandchild)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        ids = {d["id"] for d in result["descendants"]}

        self.assertNotIn(str(terminal_child.id), ids)
        self.assertNotIn(str(grandchild.id), ids)
        self.assertNotIn(str(great_grandchild.id), ids)
        # traversed_ids holds the terminal node itself and NOTHING below it —
        # nothing beneath a terminal node is even visited.
        self.assertIn(str(terminal_child.id), result["traversed_ids"])
        self.assertNotIn(str(grandchild.id), result["traversed_ids"])
        self.assertNotIn(str(great_grandchild.id), result["traversed_ids"])

    def test_pruning_applies_at_any_depth_not_just_level_one(self):
        # Case B: live child -> terminal grandchild -> live great-grandchild.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        root = _issue(ws, proj, user, state=st_started)
        child = _issue(ws, proj, user, state=st_started, parent=root)
        terminal_grandchild = _issue(ws, proj, user, state=st_completed, parent=child)
        great_grandchild = _issue(ws, proj, user, state=st_started, parent=terminal_grandchild)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        ids = {d["id"] for d in result["descendants"]}

        self.assertIn(str(child.id), ids)
        self.assertNotIn(str(terminal_grandchild.id), ids)
        self.assertNotIn(str(great_grandchild.id), ids)
        self.assertIn(str(terminal_grandchild.id), result["traversed_ids"])

    def test_stateless_child_is_not_terminal_and_keeps_being_walked(self):
        # Case C: `child.state is None` is NOT terminal (its group reads as
        # None, which is not in TERMINAL_GROUPS) — both it and its live
        # grandchild stay listed.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        root = _issue(ws, proj, user, state=st_started)
        stateless_child = _issue(ws, proj, user, state=None, parent=root)
        grandchild = _issue(ws, proj, user, state=st_started, parent=stateless_child)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        ids = {d["id"] for d in result["descendants"]}

        self.assertIn(str(stateless_child.id), ids)
        self.assertIn(str(grandchild.id), ids)

    def test_cross_project_child_resolves_its_own_project_state(self):
        ws, proj, user = self._setup()
        other_proj = _project(ws)
        _pmember(ws, other_proj, user)
        st_started = _state(ws, proj, "started")
        other_completed = _state(ws, other_proj, "completed")
        root = _issue(ws, proj, user, state=st_started)
        cross_child = _issue(ws, other_proj, user, state=_state(ws, other_proj, "started"), parent=root)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        node = result["descendants"][0]

        self.assertEqual(node["id"], str(cross_child.id))
        self.assertEqual(node["project_id"], str(other_proj.id))
        self.assertEqual(node["target_state_id"], str(other_completed.id))

    def test_project_with_no_matching_state_is_ineligible(self):
        ws, proj, user = self._setup()
        other_proj = _project(ws)
        _pmember(ws, other_proj, user)
        st_started = _state(ws, proj, "started")
        # other_proj has no "completed" state at all.
        root = _issue(ws, proj, user, state=st_started)
        child = _issue(ws, other_proj, user, state=_state(ws, other_proj, "started"), parent=root)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        node = result["descendants"][0]

        self.assertEqual(node["id"], str(child.id))
        self.assertFalse(node["eligible"])
        self.assertEqual(node["reason"], "no_matching_state")

    def test_actor_not_active_member_is_ineligible(self):
        ws, proj, user = self._setup()
        other_proj = _project(ws)
        _state(ws, other_proj, "completed")
        # deliberately no _pmember(ws, other_proj, user) — actor has no membership there.
        st_started = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st_started)
        _issue(ws, other_proj, user, state=_state(ws, other_proj, "started"), parent=root)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)
        node = result["descendants"][0]

        self.assertFalse(node["eligible"])
        self.assertEqual(node["reason"], "no_permission")

    def test_renamed_states_still_resolved_by_group_not_name(self):
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_shipped = _state(ws, proj, "completed", name="Shipped")  # renamed from "Done"
        root = _issue(ws, proj, user, state=st_started)
        _issue(ws, proj, user, state=st_started, parent=root)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)

        self.assertEqual(result["descendants"][0]["target_state_id"], str(st_shipped.id))

    def test_parent_cycle_terminates_without_recursion_error(self):
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        a = _issue(ws, proj, user, state=st)
        b = _issue(ws, proj, user, state=st, parent=a)
        # Build the cycle directly via the ORM (bypassing any app-level guard):
        # a -> parent b would be a normal two-level tree; force b -> parent a too.
        a.parent = b
        a.save(update_fields=["parent"])

        try:
            result = collect_descendants(root_issue=a, target_group="completed", actor_id=user.id)
        except RecursionError:  # pragma: no cover
            self.fail("collect_descendants recursed on a parent cycle")

        # Terminates and lists b (a's only real child) without looping forever.
        self.assertIn(str(b.id), {d["id"] for d in result["descendants"]})

    def test_max_depth_cap_sets_depth_capped_and_stops(self):
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        current = root
        # Build a chain deeper than MAX_DEPTH.
        for _ in range(MAX_DEPTH + 3):
            current = _issue(ws, proj, user, state=st, parent=current)

        result = collect_descendants(root_issue=root, target_group="completed", actor_id=user.id)

        self.assertTrue(result["depth_capped"])
        self.assertLessEqual(len(result["descendants"]), MAX_DEPTH)


# ---------------------------------------------------------------------------
# apply_cascade — the write transaction
# ---------------------------------------------------------------------------

class TestApplyCascade(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        return ws, proj, user

    def _tree(self, ws, proj, user):
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        root = _issue(ws, proj, user, state=st_started)
        c1 = _issue(ws, proj, user, state=st_started, parent=root)
        c2 = _issue(ws, proj, user, state=st_started, parent=root)
        return st_started, st_completed, root, c1, c2

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_ineligible_posted_id_is_rejected_rest_still_applies(
        self, mock_issue_activity, mock_model_activity
    ):
        ws, proj, user = self._setup()
        _st_started, st_completed, root, c1, c2 = self._tree(ws, proj, user)

        other_proj = _project(ws)  # no matching completed state here at all
        ineligible = _issue(ws, other_proj, user, state=_state(ws, other_proj, "started"), parent=root)

        result = apply_cascade(
            root_issue=root,
            state=st_completed,
            child_ids=[str(c1.id), str(ineligible.id)],
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(result["updated"], [str(c1.id)])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(result["rejected"][0]["id"], str(ineligible.id))

        c1.refresh_from_db()
        c2.refresh_from_db()
        ineligible.refresh_from_db()
        self.assertEqual(c1.state_id, st_completed.id)
        self.assertNotEqual(c2.state_id, st_completed.id)  # not requested, untouched
        self.assertNotEqual(ineligible.state_id, st_completed.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_posted_id_not_a_descendant_at_all_is_rejected(
        self, mock_issue_activity, mock_model_activity
    ):
        ws, proj, user = self._setup()
        _st_started, st_completed, root, c1, _c2 = self._tree(ws, proj, user)
        stranger = _issue(ws, proj, user, state=_state(ws, proj, "started"))  # no parent link at all

        result = apply_cascade(
            root_issue=root,
            state=st_completed,
            child_ids=[str(c1.id), str(stranger.id)],
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(result["updated"], [str(c1.id)])
        rejected_ids = {r["id"] for r in result["rejected"]}
        self.assertIn(str(stranger.id), rejected_ids)
        rejected_reason = next(r["reason"] for r in result["rejected"] if r["id"] == str(stranger.id))
        self.assertEqual(rejected_reason, "not_a_descendant")

        stranger.refresh_from_db()
        self.assertNotEqual(stranger.state_id, st_completed.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_posted_id_beneath_a_terminal_ancestor_is_rejected_and_not_written(
        self, mock_issue_activity, mock_model_activity
    ):
        # Phase 0 case D (2026-08-28): a live grandchild under a terminal
        # child is genuinely a descendant but sits behind a pruned branch, so
        # the rejection reason is `under_terminal_ancestor` — NOT
        # `not_a_descendant`, which would falsely deny tree membership.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        st_cancelled = _state(ws, proj, "cancelled")
        root = _issue(ws, proj, user, state=st_started)
        c1 = _issue(ws, proj, user, state=st_started, parent=root)
        terminal_child = _issue(ws, proj, user, state=st_cancelled, parent=root)
        hidden_grandchild = _issue(ws, proj, user, state=st_started, parent=terminal_child)

        result = apply_cascade(
            root_issue=root,
            state=st_completed,
            child_ids=[str(c1.id), str(hidden_grandchild.id)],
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(result["updated"], [str(c1.id)])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(result["rejected"][0]["id"], str(hidden_grandchild.id))
        self.assertEqual(result["rejected"][0]["reason"], "under_terminal_ancestor")

        hidden_grandchild.refresh_from_db()
        self.assertEqual(hidden_grandchild.state_id, st_started.id)  # NOT written

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_child_ids_omitted_moves_every_eligible_descendant(
        self, mock_issue_activity, mock_model_activity
    ):
        ws, proj, user = self._setup()
        _st_started, st_completed, root, c1, c2 = self._tree(ws, proj, user)

        result = apply_cascade(
            root_issue=root, state=st_completed, child_ids=None, actor_id=user.id, slug=ws.slug, origin=""
        )

        self.assertEqual(set(result["updated"]), {str(c1.id), str(c2.id)})
        c1.refresh_from_db()
        c2.refresh_from_db()
        root.refresh_from_db()
        self.assertEqual(root.state_id, st_completed.id)
        self.assertEqual(c1.state_id, st_completed.id)
        self.assertEqual(c2.state_id, st_completed.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_child_ids_empty_list_cascades_nothing_only_parent_moves(
        self, mock_issue_activity, mock_model_activity
    ):
        ws, proj, user = self._setup()
        _st_started, st_completed, root, c1, c2 = self._tree(ws, proj, user)

        result = apply_cascade(
            root_issue=root, state=st_completed, child_ids=[], actor_id=user.id, slug=ws.slug, origin=""
        )

        self.assertEqual(result["updated"], [])
        self.assertEqual(result["rejected"], [])
        root.refresh_from_db()
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertEqual(root.state_id, st_completed.id)
        self.assertNotEqual(c1.state_id, st_completed.id)
        self.assertNotEqual(c2.state_id, st_completed.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_failure_mid_way_rolls_back_the_parent_too(
        self, mock_issue_activity, mock_model_activity
    ):
        ws, proj, user = self._setup()
        _st_started, st_completed, root, c1, _c2 = self._tree(ws, proj, user)
        original_state_id = root.state_id

        with mock.patch.object(
            Issue.issue_objects, "bulk_update", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                apply_cascade(
                    root_issue=root,
                    state=st_completed,
                    child_ids=[str(c1.id)],
                    actor_id=user.id,
                    slug=ws.slug,
                    origin="",
                )

        root.refresh_from_db()
        self.assertEqual(root.state_id, original_state_id)
        mock_issue_activity.delay.assert_not_called()
        mock_model_activity.delay.assert_not_called()

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_every_cascaded_child_dispatch_carries_notification_false(
        self, mock_issue_activity, mock_model_activity
    ):
        ws, proj, user = self._setup()
        _st_started, st_completed, root, c1, c2 = self._tree(ws, proj, user)

        apply_cascade(
            root_issue=root, state=st_completed, child_ids=None, actor_id=user.id, slug=ws.slug, origin=""
        )

        child_issue_ids = {str(c1.id), str(c2.id)}
        child_calls = [
            call
            for call in mock_issue_activity.delay.call_args_list
            if call.kwargs.get("issue_id") in child_issue_ids
        ]
        self.assertEqual(len(child_calls), 2)
        for call in child_calls:
            self.assertEqual(call.kwargs.get("notification"), False)

        # The parent's own dispatch is the one exception — it DOES notify.
        parent_calls = [
            call
            for call in mock_issue_activity.delay.call_args_list
            if call.kwargs.get("issue_id") == str(root.id)
        ]
        self.assertEqual(len(parent_calls), 1)
        self.assertEqual(parent_calls[0].kwargs.get("notification"), True)
