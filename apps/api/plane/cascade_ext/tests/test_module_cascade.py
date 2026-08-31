# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# DB integration tests (real Postgres) for cascade_ext's MODULE cascade:
# collect_module_cascade (preview shape) and apply_module_cascade (the
# atomic module-status + issue-states write), plus the two HTTP endpoints.
# Mirrors test_cascade_db.py's style: TransactionTestCase + explicit ORM
# rows, no mocking the unit under test — except the dispatched Celery tasks,
# where mocking is the only way to observe the notification kwarg.
#
# Test matrix: plans/260828-module-cascade-terminal-status/phase-1-module-cascade-backend.md

import uuid
from unittest import mock

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

# Run Celery tasks inline (no broker in tests) for any test that does NOT
# explicitly mock issue_activity/model_activity itself.
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.cascade_ext.service import (
    MAX_MODULE_CASCADE_ITEMS,
    CascadeCapExceeded,
    apply_module_cascade,
    collect_module_cascade,
)
from plane.db.models import Issue


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_cascade_db.py so the files stay in sync)
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


def _module(ws, proj, status="planned", archived=False):
    from plane.db.models import Module

    return Module.objects.create(
        workspace=ws,
        project=proj,
        name=f"m-{uuid.uuid4().hex[:6]}",
        status=status,
        archived_at=timezone.now() if archived else None,
    )


def _module_issue(module, issue):
    from plane.db.models import ModuleIssue

    return ModuleIssue.objects.create(
        workspace=module.workspace, project=module.project, module=module, issue=issue
    )


# ---------------------------------------------------------------------------
# collect_module_cascade — preview shape
# ---------------------------------------------------------------------------

class TestCollectModuleCascade(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        return ws, proj, user

    def test_empty_module_returns_zero_summary_without_running_the_bfs(self):
        # Case 1: no seeds -> the zero-summary shape immediately; the ONLY
        # query is the seed lookup itself (zero BFS queries).
        ws, proj, user = self._setup()
        module = _module(ws, proj)

        with self.assertNumQueries(1):
            result = collect_module_cascade(
                module=module, target_group="completed", actor_id=user.id
            )

        self.assertEqual(result["summary"]["total_live"], 0)
        self.assertEqual(result["items"], [])
        self.assertFalse(result["over_cap"])
        self.assertFalse(result["depth_capped"])
        self.assertEqual(result["cap"], MAX_MODULE_CASCADE_ITEMS)

    def test_flat_module_lists_only_non_terminal_members_at_depth_zero(self):
        # Case 2: mixed states — terminal members are excluded (and counted),
        # live members are listed at depth 0 with is_module_member true.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_backlog = _state(ws, proj, "backlog")
        st_completed = _state(ws, proj, "completed")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        b = _issue(ws, proj, user, state=st_backlog)
        done = _issue(ws, proj, user, state=st_completed)
        for issue in (a, b, done):
            _module_issue(module, issue)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )
        by_id = {item["id"]: item for item in result["items"]}

        self.assertEqual(set(by_id.keys()), {str(a.id), str(b.id)})
        for item in by_id.values():
            self.assertEqual(item["depth"], 0)
            self.assertTrue(item["is_module_member"])
            self.assertTrue(item["eligible"])
        self.assertEqual(result["summary"]["total_live"], 2)
        self.assertEqual(result["summary"]["eligible"], 2)
        self.assertEqual(result["summary"]["already_terminal"], 1)

    def test_member_with_subtree_lists_every_level(self):
        # Case 3: member -> child -> grandchild => depth 0/1/2, and
        # is_module_member is true ONLY for the seed.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        module = _module(ws, proj)
        member = _issue(ws, proj, user, state=st_started)
        child = _issue(ws, proj, user, state=st_started, parent=member)
        grandchild = _issue(ws, proj, user, state=st_started, parent=child)
        _module_issue(module, member)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )
        by_id = {item["id"]: item for item in result["items"]}

        self.assertEqual(
            set(by_id.keys()), {str(member.id), str(child.id), str(grandchild.id)}
        )
        self.assertEqual(by_id[str(member.id)]["depth"], 0)
        self.assertEqual(by_id[str(child.id)]["depth"], 1)
        self.assertEqual(by_id[str(grandchild.id)]["depth"], 2)
        self.assertTrue(by_id[str(member.id)]["is_module_member"])
        self.assertFalse(by_id[str(child.id)]["is_module_member"])
        self.assertFalse(by_id[str(grandchild.id)]["is_module_member"])
        for item in by_id.values():
            self.assertEqual(item["target_state_id"], str(st_completed.id))

    def test_terminal_member_prunes_its_subtree(self):
        # Case 4: a completed member is excluded AND its live child is absent
        # (Phase 0's prune rule, shared with the issue cascade).
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        module = _module(ws, proj)
        done_member = _issue(ws, proj, user, state=st_completed)
        live_child = _issue(ws, proj, user, state=st_started, parent=done_member)
        _module_issue(module, done_member)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )
        ids = {item["id"] for item in result["items"]}

        self.assertNotIn(str(done_member.id), ids)
        self.assertNotIn(str(live_child.id), ids)
        self.assertEqual(result["summary"]["already_terminal"], 1)

    def test_cross_project_subitem_resolves_its_own_projects_state(self):
        # Case 6.
        ws, proj, user = self._setup()
        other_proj = _project(ws)
        _pmember(ws, other_proj, user)
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        other_completed = _state(ws, other_proj, "completed")
        module = _module(ws, proj)
        member = _issue(ws, proj, user, state=st_started)
        cross_child = _issue(
            ws, other_proj, user, state=_state(ws, other_proj, "started"), parent=member
        )
        _module_issue(module, member)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )
        by_id = {item["id"]: item for item in result["items"]}

        self.assertEqual(by_id[str(cross_child.id)]["project_id"], str(other_proj.id))
        self.assertEqual(
            by_id[str(cross_child.id)]["target_state_id"], str(other_completed.id)
        )

    def test_renamed_target_state_still_resolved_by_group_not_name(self):
        # Case 7.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_shipped = _state(ws, proj, "completed", name="Shipped")  # renamed from "Done"
        module = _module(ws, proj)
        member = _issue(ws, proj, user, state=st_started)
        _module_issue(module, member)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )

        self.assertEqual(result["items"][0]["target_state_id"], str(st_shipped.id))

    def test_subitem_in_project_actor_is_not_member_of_is_listed_ineligible(self):
        # Case 8.
        ws, proj, user = self._setup()
        other_proj = _project(ws)
        _state(ws, other_proj, "completed")
        # deliberately no _pmember(ws, other_proj, user)
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        member = _issue(ws, proj, user, state=st_started)
        cross_child = _issue(
            ws, other_proj, user, state=_state(ws, other_proj, "started"), parent=member
        )
        _module_issue(module, member)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )
        by_id = {item["id"]: item for item in result["items"]}
        node = by_id[str(cross_child.id)]

        self.assertFalse(node["eligible"])
        self.assertEqual(node["reason"], "no_permission")
        self.assertEqual(result["summary"]["ineligible"], 1)

    def test_project_with_no_state_in_target_group_is_no_matching_state(self):
        # Case 9.
        ws, proj, user = self._setup()
        other_proj = _project(ws)
        _pmember(ws, other_proj, user)
        # other_proj has NO "completed" state at all.
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        member = _issue(ws, proj, user, state=st_started)
        cross_child = _issue(
            ws, other_proj, user, state=_state(ws, other_proj, "started"), parent=member
        )
        _module_issue(module, member)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )
        by_id = {item["id"]: item for item in result["items"]}

        self.assertFalse(by_id[str(cross_child.id)]["eligible"])
        self.assertEqual(by_id[str(cross_child.id)]["reason"], "no_matching_state")

    def test_parent_cycle_among_module_members_terminates_without_duplicates(self):
        # Case 10: both seeds are in `visited` before the walk starts, so the
        # cycle a <-> b is never followed.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        b = _issue(ws, proj, user, state=st_started, parent=a)
        a.parent = b
        a.save(update_fields=["parent"])
        _module_issue(module, a)
        _module_issue(module, b)

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )
        ids = [item["id"] for item in result["items"]]

        self.assertEqual(sorted(ids), sorted([str(a.id), str(b.id)]))  # no dupes

    def test_over_cap_preview_reports_real_total_and_empties_items(self):
        # Case 16 (preview half): 101 live members — over the 100 cap.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        issues = Issue.objects.bulk_create(
            [
                Issue(
                    workspace=ws,
                    project=proj,
                    name=f"bulk-{i}",
                    created_by=user,
                    state=st_started,
                    sequence_id=i + 1,
                )
                for i in range(MAX_MODULE_CASCADE_ITEMS + 1)
            ]
        )
        from plane.db.models import ModuleIssue

        ModuleIssue.objects.bulk_create(
            [
                ModuleIssue(workspace=ws, project=proj, module=module, issue=issue)
                for issue in issues
            ]
        )

        result = collect_module_cascade(
            module=module, target_group="completed", actor_id=user.id
        )

        self.assertTrue(result["over_cap"])
        self.assertEqual(result["items"], [])
        self.assertEqual(
            result["summary"]["total_live"], MAX_MODULE_CASCADE_ITEMS + 1
        )

    def test_query_count_on_a_flat_50_item_module_has_no_n_plus_one(self):
        # Case 20: the whole preview is a FIXED number of queries regardless
        # of item count — seed lookup, seed fetch, one BFS children query
        # (empty -> break), one State query, one ProjectMember query.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        issues = Issue.objects.bulk_create(
            [
                Issue(
                    workspace=ws,
                    project=proj,
                    name=f"q-{i}",
                    created_by=user,
                    state=st_started,
                    sequence_id=i + 1,
                )
                for i in range(50)
            ]
        )
        from plane.db.models import ModuleIssue

        ModuleIssue.objects.bulk_create(
            [
                ModuleIssue(workspace=ws, project=proj, module=module, issue=issue)
                for issue in issues
            ]
        )

        with self.assertNumQueries(5):
            result = collect_module_cascade(
                module=module, target_group="completed", actor_id=user.id
            )
        self.assertEqual(result["summary"]["total_live"], 50)


# ---------------------------------------------------------------------------
# apply_module_cascade — the atomic module + issues write
# ---------------------------------------------------------------------------

class TestApplyModuleCascade(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        return ws, proj, user

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_cancelling_a_module_leaves_a_completed_member_untouched(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 5: the completed member is in the OTHER terminal group — M8
        # says it is never overwritten.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        st_cancelled = _state(ws, proj, "cancelled")
        module = _module(ws, proj)
        done = _issue(ws, proj, user, state=st_completed)
        live1 = _issue(ws, proj, user, state=st_started)
        live2 = _issue(ws, proj, user, state=st_started)
        for issue in (done, live1, live2):
            _module_issue(module, issue)

        result = apply_module_cascade(
            module=module,
            status="cancelled",
            item_ids=None,
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(set(result["updated"]), {str(live1.id), str(live2.id)})
        module.refresh_from_db()
        done.refresh_from_db()
        live1.refresh_from_db()
        live2.refresh_from_db()
        self.assertEqual(module.status, "cancelled")
        self.assertEqual(done.state_id, st_completed.id)  # untouched
        self.assertEqual(live1.state_id, st_cancelled.id)
        self.assertEqual(live2.state_id, st_cancelled.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_item_ids_none_moves_every_eligible_item(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 11.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        child = _issue(ws, proj, user, state=st_started, parent=a)
        _module_issue(module, a)

        result = apply_module_cascade(
            module=module,
            status="completed",
            item_ids=None,
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(set(result["updated"]), {str(a.id), str(child.id)})
        module.refresh_from_db()
        a.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(module.status, "completed")
        self.assertEqual(a.state_id, st_completed.id)
        self.assertEqual(child.state_id, st_completed.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_item_ids_empty_list_moves_only_the_module(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 12: an explicit [] is NOT "all" — zero issue writes.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        _module_issue(module, a)

        result = apply_module_cascade(
            module=module,
            status="completed",
            item_ids=[],
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(result["updated"], [])
        self.assertEqual(result["rejected"], [])
        module.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual(module.status, "completed")
        self.assertNotEqual(a.state_id, st_completed.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_posted_ineligible_id_is_rejected_with_its_reason_and_not_written(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 13: the module's own project has NO completed state, so its
        # member is listed ineligible; posting its id rejects, not writes.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        _module_issue(module, a)

        result = apply_module_cascade(
            module=module,
            status="completed",
            item_ids=[str(a.id)],
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(result["updated"], [])
        self.assertEqual(
            result["rejected"], [{"id": str(a.id), "reason": "no_matching_state"}]
        )
        a.refresh_from_db()
        self.assertEqual(a.state_id, st_started.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_posted_id_from_a_different_module_is_not_in_module_tree(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 14.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        other_module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        foreign = _issue(ws, proj, user, state=st_started)
        _module_issue(module, a)
        _module_issue(other_module, foreign)

        result = apply_module_cascade(
            module=module,
            status="completed",
            item_ids=[str(a.id), str(foreign.id)],
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(result["updated"], [str(a.id)])
        self.assertEqual(
            result["rejected"], [{"id": str(foreign.id), "reason": "not_in_module_tree"}]
        )
        foreign.refresh_from_db()
        self.assertEqual(foreign.state_id, st_started.id)

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_posted_id_beneath_a_terminal_member_is_under_terminal_ancestor(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 14b: Phase 0's rejection reason, reused verbatim. The live
        # child genuinely IS in the module tree — behind a pruned branch.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        module = _module(ws, proj)
        done_member = _issue(ws, proj, user, state=st_completed)
        hidden_child = _issue(ws, proj, user, state=st_started, parent=done_member)
        _module_issue(module, done_member)

        result = apply_module_cascade(
            module=module,
            status="completed",
            item_ids=[str(hidden_child.id)],
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        self.assertEqual(result["updated"], [])
        self.assertEqual(
            result["rejected"],
            [{"id": str(hidden_child.id), "reason": "under_terminal_ancestor"}],
        )
        hidden_child.refresh_from_db()
        self.assertEqual(hidden_child.state_id, st_started.id)  # NOT written

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_failure_mid_bulk_update_rolls_back_the_module_status_too(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 15: the atomicity gate for M5 — module status and issue writes
        # share ONE transaction.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        _module_issue(module, a)

        with mock.patch.object(
            Issue.issue_objects, "bulk_update", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                apply_module_cascade(
                    module=module,
                    status="completed",
                    item_ids=None,
                    actor_id=user.id,
                    slug=ws.slug,
                    origin="",
                )

        module.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual(module.status, "planned")  # rolled back
        self.assertEqual(a.state_id, st_started.id)
        mock_issue_activity.delay.assert_not_called()
        mock_model_activity.delay.assert_not_called()

    def test_over_cap_apply_raises_before_writing_anything(self):
        # Case 16 (apply half): the exception fires BEFORE any transaction
        # opens — the module's status is part of "nothing is written".
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        issues = Issue.objects.bulk_create(
            [
                Issue(
                    workspace=ws,
                    project=proj,
                    name=f"cap-{i}",
                    created_by=user,
                    state=st_started,
                    sequence_id=i + 1,
                )
                for i in range(MAX_MODULE_CASCADE_ITEMS + 1)
            ]
        )
        from plane.db.models import ModuleIssue

        ModuleIssue.objects.bulk_create(
            [
                ModuleIssue(workspace=ws, project=proj, module=module, issue=issue)
                for issue in issues
            ]
        )

        with self.assertRaises(CascadeCapExceeded) as ctx:
            apply_module_cascade(
                module=module,
                status="completed",
                item_ids=None,
                actor_id=user.id,
                slug=ws.slug,
                origin="",
            )

        self.assertEqual(ctx.exception.total_live, MAX_MODULE_CASCADE_ITEMS + 1)
        module.refresh_from_db()
        self.assertEqual(module.status, "planned")  # unchanged

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_activity_dispatch_one_module_activity_and_silent_item_activities(
        self, mock_issue_activity, mock_model_activity
    ):
        # Case 19: one model_activity for the module; per accepted item one
        # issue_activity with notification=False (load-bearing, M11) plus one
        # model_activity(model_name="issue").
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        b = _issue(ws, proj, user, state=st_started)
        _module_issue(module, a)
        _module_issue(module, b)

        apply_module_cascade(
            module=module,
            status="completed",
            item_ids=None,
            actor_id=user.id,
            slug=ws.slug,
            origin="",
        )

        module_calls = [
            c for c in mock_model_activity.delay.call_args_list
            if c.kwargs.get("model_name") == "module"
        ]
        self.assertEqual(len(module_calls), 1)
        self.assertEqual(module_calls[0].kwargs["model_id"], str(module.id))

        item_ids = {str(a.id), str(b.id)}
        issue_activity_calls = [
            c for c in mock_issue_activity.delay.call_args_list
            if c.kwargs.get("issue_id") in item_ids
        ]
        self.assertEqual(len(issue_activity_calls), 2)
        for call in issue_activity_calls:
            self.assertEqual(call.kwargs.get("notification"), False)

        issue_model_calls = [
            c for c in mock_model_activity.delay.call_args_list
            if c.kwargs.get("model_name") == "issue"
            and c.kwargs.get("model_id") in item_ids
        ]
        self.assertEqual(len(issue_model_calls), 2)


# ---------------------------------------------------------------------------
# The two HTTP endpoints — auth gate, validation, archived/cap refusal
# ---------------------------------------------------------------------------

class TestModuleCascadeEndpoints(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        return ws, proj, user

    def _preview_url(self, ws, proj, module):
        return (
            f"/api/cascade-ext/workspaces/{ws.slug}/projects/{proj.id}"
            f"/modules/{module.id}/cascade-preview/"
        )

    def _apply_url(self, ws, proj, module):
        return (
            f"/api/cascade-ext/workspaces/{ws.slug}/projects/{proj.id}"
            f"/modules/{module.id}/cascade-apply/"
        )

    def test_preview_rejects_a_non_terminal_status(self):
        # Case 18.
        ws, proj, _user_ = self._setup()
        module = _module(ws, proj)

        resp = self.client.get(self._preview_url(ws, proj, module) + "?status=in-progress")

        self.assertEqual(resp.status_code, 400)

    def test_archived_module_refuses_preview_and_apply(self):
        # Case 17 (M13).
        ws, proj, _user_ = self._setup()
        module = _module(ws, proj, archived=True)

        preview = self.client.get(self._preview_url(ws, proj, module) + "?status=completed")
        apply_resp = self.client.post(
            self._apply_url(ws, proj, module), {"status": "completed"}, format="json"
        )

        self.assertEqual(preview.status_code, 400)
        self.assertEqual(apply_resp.status_code, 400)

    def test_apply_over_cap_is_a_400_and_writes_nothing(self):
        # Case 16 (endpoint half): exact contract body, module status
        # unchanged.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        issues = Issue.objects.bulk_create(
            [
                Issue(
                    workspace=ws,
                    project=proj,
                    name=f"http-cap-{i}",
                    created_by=user,
                    state=st_started,
                    sequence_id=i + 1,
                )
                for i in range(MAX_MODULE_CASCADE_ITEMS + 1)
            ]
        )
        from plane.db.models import ModuleIssue

        ModuleIssue.objects.bulk_create(
            [
                ModuleIssue(workspace=ws, project=proj, module=module, issue=issue)
                for issue in issues
            ]
        )

        resp = self.client.post(
            self._apply_url(ws, proj, module), {"status": "completed"}, format="json"
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "cascade exceeds MAX_MODULE_CASCADE_ITEMS")
        self.assertEqual(resp.json()["total_live"], MAX_MODULE_CASCADE_ITEMS + 1)
        self.assertEqual(resp.json()["cap"], MAX_MODULE_CASCADE_ITEMS)
        module.refresh_from_db()
        self.assertEqual(module.status, "planned")

    @mock.patch("plane.cascade_ext.service.model_activity")
    @mock.patch("plane.cascade_ext.service.issue_activity")
    def test_happy_path_apply_over_http(self, mock_issue_activity, mock_model_activity):
        # Smoke: the endpoint wires through to the service and returns the
        # contract shape.
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        _state(ws, proj, "completed")
        module = _module(ws, proj)
        a = _issue(ws, proj, user, state=st_started)
        _module_issue(module, a)

        resp = self.client.post(
            self._apply_url(ws, proj, module), {"status": "completed"}, format="json"
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["module"], str(module.id))
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["updated"], [str(a.id)])
        self.assertEqual(body["rejected"], [])
