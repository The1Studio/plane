# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# DB integration tests (real Postgres) for the parent-issue rollup: the
# recursive CTE math, PUT-block, single-GET, bulk endpoint authz, and the
# matrix double-count regression. Mirrors the test_workload_db.py /
# test_workload_bulk.py style: TransactionTestCase + explicit ORM rows, real
# Postgres, no mocking the unit under test.

import uuid
from datetime import date

from django.test import TransactionTestCase
from rest_framework.test import APIClient

# Run Celery tasks inline (no broker in tests).
try:  # pragma: no cover
    from plane.celery import app as _celery_app

    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = False
except Exception:  # pragma: no cover
    pass

from plane.workload.rollup import MAX_DEPTH, compute_rollups, is_parent, parent_issue_ids
from plane.workload.service import BULK_ESTIMATES_CAP, compute_workload


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_workload_db.py / test_workload_bulk.py)
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


def _project(ws, guest_view_all=False):
    from plane.db.models import Project

    proj = Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
    )
    if guest_view_all:
        proj.guest_view_all_features = True
        proj.save()
    return proj


def _pmember(ws, proj, user, role=15, is_active=True):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(
        workspace=ws, project=proj, member=user, role=role, is_active=is_active
    )


def _wmember(ws, user, role=20):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(
        workspace=ws, member=user, role=role, is_active=True
    )


def _state(ws, proj, group="started"):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws,
        project=proj,
        name=f"{group}-{uuid.uuid4().hex[:4]}",
        color="#fff",
        group=group,
    )


def _issue(ws, proj, created_by, state=None, parent=None, target=None, start=None):
    from plane.db.models import Issue

    return Issue.objects.create(
        workspace=ws,
        project=proj,
        name=f"i-{uuid.uuid4().hex[:6]}",
        created_by=created_by,
        state=state,
        parent=parent,
        target_date=target,
        start_date=start,
        sequence_id=1,
    )


def _assign(ws, proj, issue, user):
    from plane.db.models import IssueAssignee

    return IssueAssignee.objects.create(
        workspace=ws, project=proj, issue=issue, assignee=user
    )


def _estimate(ws, proj, issue, hours):
    from plane.workload.models import WorkloadEstimate

    return WorkloadEstimate.objects.create(
        workspace=ws, project=proj, issue=issue, hours=hours
    )


# ---------------------------------------------------------------------------
# Rollup math
# ---------------------------------------------------------------------------

class TestRollupMath(TransactionTestCase):
    def _setup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        return ws, proj, user

    def test_two_level_tree_hours_done_percent(self):
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_completed = _state(ws, proj, "completed")
        root = _issue(ws, proj, user, state=st_started)
        c1 = _issue(ws, proj, user, state=st_started, parent=root)
        c2 = _issue(ws, proj, user, state=st_completed, parent=root)
        _estimate(ws, proj, c1, 3.0)
        _estimate(ws, proj, c2, 2.0)

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["hours"], 5.0)
        self.assertEqual(result["done_hours"], 2.0)
        self.assertEqual(result["percent"], 0.4)
        self.assertEqual(result["leaf_count"], 2)

    def test_three_level_tree_only_leaves_carry_hours(self):
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        mid = _issue(ws, proj, user, state=st, parent=root)
        leaf = _issue(ws, proj, user, state=st, parent=mid)
        _estimate(ws, proj, leaf, 4.0)
        # Mid also has a legacy estimate — must be ignored (mid is not a leaf).
        _estimate(ws, proj, mid, 99.0)

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["hours"], 4.0)
        self.assertEqual(result["leaf_count"], 1)

    def test_cancelled_child_excluded(self):
        ws, proj, user = self._setup()
        st_cancelled = _state(ws, proj, "cancelled")
        root = _issue(ws, proj, user, state=_state(ws, proj, "started"))
        child = _issue(ws, proj, user, state=st_cancelled, parent=root)
        _estimate(ws, proj, child, 5.0)

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["hours"], 0.0)
        self.assertEqual(result["leaf_count"], 0)
        self.assertIsNone(result["percent"])

    def test_triage_child_excluded(self):
        ws, proj, user = self._setup()
        st_triage = _state(ws, proj, "triage")
        root = _issue(ws, proj, user, state=_state(ws, proj, "started"))
        child = _issue(ws, proj, user, state=st_triage, parent=root)
        _estimate(ws, proj, child, 5.0)

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["hours"], 0.0)
        self.assertEqual(result["leaf_count"], 0)

    def test_null_state_child_is_countable(self):
        """State is optional on Issue — a null-state issue must still count
        (LEFT JOIN in the CTE, explicit OR in countable_issue_q())."""
        ws, proj, user = self._setup()
        root = _issue(ws, proj, user, state=_state(ws, proj, "started"))
        child = _issue(ws, proj, user, state=None, parent=root)
        _estimate(ws, proj, child, 4.0)

        self.assertTrue(is_parent(root.id))
        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]
        self.assertEqual(result["hours"], 4.0)
        self.assertEqual(result["leaf_count"], 1)

    def test_due_date_is_max_over_all_countable_descendants(self):
        """due_date = max target_date over ALL countable descendants
        (intermediate node's date counts even though it has no estimate)."""
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        early_date = date(2026, 6, 1)
        late_date = date(2026, 8, 1)
        mid = _issue(ws, proj, user, state=st, parent=root, target=late_date)
        leaf = _issue(ws, proj, user, state=st, parent=mid, target=early_date)
        _estimate(ws, proj, leaf, 2.0)

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["due_date"], late_date.isoformat())
        self.assertEqual(result["hours"], 2.0)  # mid has no estimate — hours unaffected

    def test_all_children_cancelled_reverts_to_leaf(self):
        ws, proj, user = self._setup()
        st_cancelled = _state(ws, proj, "cancelled")
        root = _issue(ws, proj, user, state=_state(ws, proj, "started"))
        _issue(ws, proj, user, state=st_cancelled, parent=root)

        self.assertFalse(is_parent(root.id))

    def test_noncountable_intermediate_node_prunes_subtree(self):
        """GP -> cancelled P -> countable C: GP's rollup must EXCLUDE C
        entirely (the cancelled node prunes its whole subtree — the CTE
        never reaches C because it never emits the cancelled parent row)."""
        ws, proj, user = self._setup()
        st_started = _state(ws, proj, "started")
        st_cancelled = _state(ws, proj, "cancelled")
        gp = _issue(ws, proj, user, state=st_started)
        p = _issue(ws, proj, user, state=st_cancelled, parent=gp)
        c = _issue(ws, proj, user, state=st_started, parent=p)
        _estimate(ws, proj, c, 7.0)

        result = compute_rollups(user, ws.slug, [gp.id])[str(gp.id)]

        self.assertEqual(result["hours"], 0.0)
        self.assertEqual(result["leaf_count"], 0)
        self.assertIsNone(result["due_date"])

    def test_zero_hour_leaf_contributes_nothing(self):
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        leaf = _issue(ws, proj, user, state=st, parent=root)
        _estimate(ws, proj, leaf, 0.0)

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["hours"], 0.0)
        self.assertEqual(result["leaf_count"], 0)

    def test_cents_math_exact(self):
        """3x 0.1h must sum to exactly 0.3 (integer-cents reconciliation)."""
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        for _ in range(3):
            leaf = _issue(ws, proj, user, state=st, parent=root)
            _estimate(ws, proj, leaf, 0.1)

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["hours"], 0.3)
        self.assertEqual(result["leaf_count"], 3)

    def test_percent_is_none_when_all_leaves_zero_hour(self):
        """A parent whose leaves are ALL zero-hour must report percent=None
        (never a 0/0 division or a spurious 0.0)."""
        ws, proj, user = self._setup()
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        for _ in range(2):
            leaf = _issue(ws, proj, user, state=st, parent=root)
            _estimate(ws, proj, leaf, 0.0)

        self.assertTrue(is_parent(root.id))
        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertIsNone(result["percent"])
        self.assertEqual(result["hours"], 0.0)
        self.assertEqual(result["done_hours"], 0.0)


# ---------------------------------------------------------------------------
# Nested roots — per-root anchoring
# ---------------------------------------------------------------------------

class TestNestedRoots(TransactionTestCase):
    def test_root_and_its_descendant_both_get_independent_rollups(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")

        a = _issue(ws, proj, user, state=st)
        b = _issue(ws, proj, user, state=st, parent=a)
        c = _issue(ws, proj, user, state=st, parent=b)
        d = _issue(ws, proj, user, state=st, parent=b)
        _estimate(ws, proj, c, 2.0)
        _estimate(ws, proj, d, 3.0)

        results = compute_rollups(user, ws.slug, [a.id, b.id])

        self.assertEqual(results[str(a.id)]["hours"], 5.0)
        self.assertEqual(results[str(a.id)]["leaf_count"], 2)
        self.assertEqual(results[str(b.id)]["hours"], 5.0)
        self.assertEqual(results[str(b.id)]["leaf_count"], 2)


# ---------------------------------------------------------------------------
# Drift guard — ORM is_parent vs CTE-derived countability must agree
# ---------------------------------------------------------------------------

class TestDriftGuard(TransactionTestCase):
    def test_orm_and_cte_agree_on_countable_children(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st_started = _state(ws, proj, "started")
        st_cancelled = _state(ws, proj, "cancelled")
        st_triage = _state(ws, proj, "triage")

        root = _issue(ws, proj, user, state=st_started)
        countable_child = _issue(ws, proj, user, state=st_started, parent=root)
        _issue(ws, proj, user, state=st_cancelled, parent=root)
        _issue(ws, proj, user, state=st_triage, parent=root)
        _estimate(ws, proj, countable_child, 6.0)

        self.assertTrue(is_parent(root.id))
        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]
        self.assertEqual(result["leaf_count"], 1)
        self.assertEqual(result["hours"], 6.0)

    def test_orm_and_cte_agree_on_no_countable_children(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st_cancelled = _state(ws, proj, "cancelled")
        st_triage = _state(ws, proj, "triage")

        root = _issue(ws, proj, user, state=_state(ws, proj, "started"))
        _issue(ws, proj, user, state=st_cancelled, parent=root)
        _issue(ws, proj, user, state=st_triage, parent=root)

        self.assertFalse(is_parent(root.id))
        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]
        self.assertEqual(result["hours"], 0.0)
        self.assertEqual(result["leaf_count"], 0)


# ---------------------------------------------------------------------------
# Depth cap
# ---------------------------------------------------------------------------

class TestDepthCap(TransactionTestCase):
    def test_chain_of_twelve_counted_only_to_depth_ten(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")

        root = _issue(ws, proj, user, state=st)
        parent = root
        nodes = []
        for _ in range(12):
            node = _issue(ws, proj, user, state=st, parent=parent)
            nodes.append(node)
            parent = node
        # nodes[9] is the 10th descendant (depth == MAX_DEPTH); nodes[11] is
        # the 12th (depth == MAX_DEPTH + 2, unreachable).
        self.assertEqual(MAX_DEPTH, 10)
        _estimate(ws, proj, nodes[9], 3.0)   # depth 10 — reachable
        _estimate(ws, proj, nodes[11], 1.0)  # depth 12 — beyond the cap

        result = compute_rollups(user, ws.slug, [root.id])[str(root.id)]

        self.assertEqual(result["hours"], 3.0)
        self.assertEqual(result["leaf_count"], 1)


# ---------------------------------------------------------------------------
# PUT block + single-GET
# ---------------------------------------------------------------------------

class TestPutBlockAndGet(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, ws, proj, issue):
        return (
            f"/api/workspaces/{ws.slug}/projects/{proj.id}"
            f"/issues/{issue.id}/workload-estimate/"
        )

    def test_put_on_parent_returns_400_with_error_code(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        _issue(ws, proj, user, state=st, parent=root)  # countable child

        self.client.force_authenticate(user=user)
        resp = self.client.put(self._url(ws, proj, root), {"hours": 5.0}, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error_code"], "PARENT_HAS_CHILDREN")
        self.assertIn("error", resp.data)

    def test_put_on_leaf_returns_200(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        leaf = _issue(ws, proj, user, state=st)

        self.client.force_authenticate(user=user)
        resp = self.client.put(self._url(ws, proj, leaf), {"hours": 5.0}, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["hours"], 5.0)

    def test_put_on_parent_of_only_cancelled_returns_200(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st_cancelled = _state(ws, proj, "cancelled")
        root = _issue(ws, proj, user, state=_state(ws, proj, "started"))
        _issue(ws, proj, user, state=st_cancelled, parent=root)

        self.client.force_authenticate(user=user)
        resp = self.client.put(self._url(ws, proj, root), {"hours": 5.0}, format="json")

        self.assertEqual(resp.status_code, 200)

    def test_get_on_parent_returns_null_hours_and_rollup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        child = _issue(ws, proj, user, state=st, parent=root)
        _estimate(ws, proj, child, 3.0)
        _estimate(ws, proj, root, 99.0)  # legacy — must be hidden once a parent

        self.client.force_authenticate(user=user)
        resp = self.client.get(self._url(ws, proj, root))

        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["hours"])
        self.assertTrue(resp.data["is_parent"])
        self.assertEqual(resp.data["rollup"]["hours"], 3.0)
        self.assertEqual(resp.data["rollup"]["leaf_count"], 1)

    def test_get_on_leaf_is_unaffected(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        leaf = _issue(ws, proj, user, state=st)
        _estimate(ws, proj, leaf, 5.0)

        self.client.force_authenticate(user=user)
        resp = self.client.get(self._url(ws, proj, leaf))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["hours"], 5.0)
        self.assertFalse(resp.data["is_parent"])
        self.assertNotIn("rollup", resp.data)

    def test_delete_on_parent_returns_204(self):
        """DELETE stays allowed on parents (cleanup) — only PUT is hard-blocked."""
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user, role=20)  # DELETE requires ROLE.ADMIN
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        _issue(ws, proj, user, state=st, parent=root)  # countable child
        _estimate(ws, proj, root, 99.0)  # legacy row to actually delete

        self.client.force_authenticate(user=user)
        resp = self.client.delete(self._url(ws, proj, root))

        self.assertEqual(resp.status_code, 204)


# ---------------------------------------------------------------------------
# Matrix double-count regression
# ---------------------------------------------------------------------------

class TestMatrixLeafOnlyFix(TransactionTestCase):
    def test_parent_and_child_both_estimated_only_child_counted(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        win_from, win_to = date(2026, 1, 1), date(2026, 12, 31)
        d = date(2026, 6, 1)

        parent = _issue(ws, proj, user, state=st, start=d, target=d)
        child = _issue(ws, proj, user, state=st, parent=parent, start=d, target=d)
        _assign(ws, proj, parent, user)
        _assign(ws, proj, child, user)
        _estimate(ws, proj, parent, 10.0)
        _estimate(ws, proj, child, 4.0)

        data = compute_workload(user, ws.slug, "day", win_from, win_to)

        self.assertEqual(data["meta"]["issues_counted"], 1)  # parent excluded
        bucket_total = sum(v for row in data["rows"] for v in row["buckets"].values())
        self.assertEqual(bucket_total, 4.0)


# ---------------------------------------------------------------------------
# Bulk rollups endpoint
# ---------------------------------------------------------------------------

class TestBulkRollupsEndpoint(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, slug, issue_ids):
        return f"/api/workspaces/{slug}/workload-rollups/?issue_ids={','.join(str(i) for i in issue_ids)}"

    def test_empty_issue_ids_400(self):
        ws = _ws()
        user = _user()
        _wmember(ws, user, role=15)
        self.client.force_authenticate(user=user)

        resp = self.client.get(f"/api/workspaces/{ws.slug}/workload-rollups/?issue_ids=")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_cap_exceeded_400(self):
        ws = _ws()
        user = _user()
        _wmember(ws, user, role=15)
        self.client.force_authenticate(user=user)
        oversized = [uuid.uuid4() for _ in range(BULK_ESTIMATES_CAP + 1)]

        resp = self.client.get(self._url(ws.slug, oversized))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_non_parent_ids_omitted(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _wmember(ws, user, role=15)
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        leaf = _issue(ws, proj, user, state=st)

        self.client.force_authenticate(user=user)
        resp = self.client.get(self._url(ws.slug, [leaf.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(str(leaf.id), resp.data)

    def test_only_leaf_ids_returns_empty_dict_not_400(self):
        """A non-empty issue_ids list containing ONLY leaf (non-parent) ids
        must be a normal 200 {} — distinct from the empty-issue_ids-list 400."""
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _wmember(ws, user, role=15)
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        leaf1 = _issue(ws, proj, user, state=st)
        leaf2 = _issue(ws, proj, user, state=st)

        self.client.force_authenticate(user=user)
        resp = self.client.get(self._url(ws.slug, [leaf1.id, leaf2.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {})

    def test_403_for_non_member(self):
        """A user not in the workspace gets 403 (mirrors TestBulkEstimatesHTTP)."""
        ws = _ws()
        outsider = _user()
        # outsider has NO WorkspaceMember row
        self.client.force_authenticate(user=outsider)

        resp = self.client.get(self._url(ws.slug, [uuid.uuid4()]))

        self.assertEqual(resp.status_code, 403)

    def test_exactly_cap_size_does_not_raise(self):
        """The cap boundary is exclusive: len == BULK_ESTIMATES_CAP is allowed
        (mirrors TestBulkEstimatesValidation.test_exactly_cap_size_does_not_raise)."""
        ws = _ws()
        user = _user()
        _wmember(ws, user, role=15)
        self.client.force_authenticate(user=user)
        at_cap = [uuid.uuid4() for _ in range(BULK_ESTIMATES_CAP)]

        resp = self.client.get(self._url(ws.slug, at_cap))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {})

    def test_parent_id_included_with_rollup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _wmember(ws, user, role=15)
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        child = _issue(ws, proj, user, state=st, parent=root)
        _estimate(ws, proj, child, 6.0)

        self.client.force_authenticate(user=user)
        resp = self.client.get(self._url(ws.slug, [root.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(root.id), resp.data)
        self.assertEqual(resp.data[str(root.id)]["hours"], 6.0)

    def test_flag_off_guest_sees_only_own_parent(self):
        """Restricted guest: parent assigned to the guest is included; a
        parent assigned to someone else is OMITTED entirely (not zeroed)."""
        ws = _ws()
        proj = _project(ws)  # guest_view_all_features defaults to False
        guest = _user()
        other = _user()
        _wmember(ws, guest, role=5)
        _wmember(ws, other, role=15)
        _pmember(ws, proj, guest, role=5)
        _pmember(ws, proj, other, role=15)
        st = _state(ws, proj, "started")

        p_own = _issue(ws, proj, guest, state=st)
        c_own = _issue(ws, proj, guest, state=st, parent=p_own)
        _assign(ws, proj, p_own, guest)
        _estimate(ws, proj, c_own, 2.0)

        p_other = _issue(ws, proj, other, state=st)
        c_other = _issue(ws, proj, other, state=st, parent=p_other)
        _assign(ws, proj, p_other, other)
        _estimate(ws, proj, c_other, 9.0)

        self.client.force_authenticate(user=guest)
        resp = self.client.get(self._url(ws.slug, [p_own.id, p_other.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(p_own.id), resp.data)
        self.assertNotIn(str(p_other.id), resp.data)

    def test_cross_project_descendant_excluded_for_non_member(self):
        """A root's countable child living in a project the caller can't see
        must be excluded from that root's rollup — the root's OWN in-scope
        leaf still counts (partial-by-scope, not an omission of the root)."""
        ws = _ws()
        proj_a = _project(ws)
        proj_b = _project(ws)
        member = _user()
        other = _user()
        _wmember(ws, member, role=15)
        _pmember(ws, proj_a, member)  # member NOT in proj_b
        _pmember(ws, proj_b, other)
        st_a = _state(ws, proj_a, "started")
        st_b = _state(ws, proj_b, "started")

        root = _issue(ws, proj_a, member, state=st_a)
        visible_leaf = _issue(ws, proj_a, member, state=st_a, parent=root)
        _estimate(ws, proj_a, visible_leaf, 2.0)
        hidden_leaf = _issue(ws, proj_b, other, state=st_b, parent=root)
        _estimate(ws, proj_b, hidden_leaf, 7.0)

        self.client.force_authenticate(user=member)
        resp = self.client.get(self._url(ws.slug, [root.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(root.id), resp.data)
        self.assertEqual(resp.data[str(root.id)]["hours"], 2.0)
        self.assertEqual(resp.data[str(root.id)]["leaf_count"], 1)

    def test_workspace_admin_sees_all(self):
        ws = _ws()
        proj = _project(ws)
        admin = _user()
        _wmember(ws, admin, role=20)
        other = _user()
        _pmember(ws, proj, other)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, other, state=st)
        child = _issue(ws, proj, other, state=st, parent=root)
        _estimate(ws, proj, child, 5.0)

        self.client.force_authenticate(user=admin)
        resp = self.client.get(self._url(ws.slug, [root.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data[str(root.id)]["hours"], 5.0)


# ---------------------------------------------------------------------------
# Public API (/api/v1/) mirror — shape parity with the app API
# ---------------------------------------------------------------------------

class TestPublicApiMirrorShape(TransactionTestCase):
    """Round-5 addition: the /api/v1/ mirror must return the SAME shape as
    the app API for both the new bulk-rollups endpoint and the extended
    single-GET (is_parent/rollup/hours:null). Precedent:
    test_workload_bulk.py::TestBulkEstimatesRouting (routing only) — this
    class additionally exercises the full HTTP shape, same force_authenticate
    pattern as TestBulkEstimatesHTTP (DRF's force_authenticate bypasses the
    view's declared authentication_classes, so it works against the API-key
    -authenticated public API views too)."""

    def setUp(self):
        self.client = APIClient()

    def _estimate_url(self, ws, proj, issue):
        return (
            f"/api/v1/workspaces/{ws.slug}/projects/{proj.id}"
            f"/issues/{issue.id}/workload-estimate/"
        )

    def _rollups_url(self, slug, issue_ids):
        ids = ",".join(str(i) for i in issue_ids)
        return f"/api/v1/workspaces/{slug}/workload-rollups/?issue_ids={ids}"

    def test_single_get_mirror_returns_is_parent_and_rollup(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        child = _issue(ws, proj, user, state=st, parent=root)
        _estimate(ws, proj, child, 3.0)

        self.client.force_authenticate(user=user)
        resp = self.client.get(self._estimate_url(ws, proj, root))

        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["hours"])
        self.assertTrue(resp.data["is_parent"])
        self.assertEqual(resp.data["rollup"]["hours"], 3.0)

    def test_rollups_bulk_mirror_returns_same_shape(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _wmember(ws, user, role=15)
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        child = _issue(ws, proj, user, state=st, parent=root)
        _estimate(ws, proj, child, 6.0)

        self.client.force_authenticate(user=user)
        resp = self.client.get(self._rollups_url(ws.slug, [root.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data[str(root.id)]["hours"], 6.0)


# ---------------------------------------------------------------------------
# Bulk estimates: parent rows omitted (round-5)
# ---------------------------------------------------------------------------

class TestBulkEstimatesOmitsParents(TransactionTestCase):
    """Round-5 plan MAJOR-B.1: bulk_estimates (service.py) must omit rows
    whose issue is a parent — keep-but-ignore means ignored everywhere; a
    parent now looks like "no estimate" here, same as the matrix."""

    def test_parent_row_omitted_leaf_row_present(self):
        from plane.workload.service import bulk_estimates

        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        child = _issue(ws, proj, user, state=st, parent=root)
        _estimate(ws, proj, root, 99.0)  # legacy — must be omitted
        _estimate(ws, proj, child, 3.0)  # leaf — must be present
        other_leaf = _issue(ws, proj, user, state=st)
        _estimate(ws, proj, other_leaf, 1.5)

        result = bulk_estimates(user, ws.slug, [root.id, child.id, other_leaf.id])

        self.assertNotIn(str(root.id), result)
        self.assertEqual(result[str(child.id)], 3.0)
        self.assertEqual(result[str(other_leaf.id)], 1.5)

    def test_all_children_cancelled_parent_row_reappears(self):
        """Consistent with is_parent reverting to leaf when all children are
        cancelled — the legacy estimate resurfaces (decided behavior, §0)."""
        from plane.workload.service import bulk_estimates

        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st_cancelled = _state(ws, proj, "cancelled")
        root = _issue(ws, proj, user, state=_state(ws, proj, "started"))
        _issue(ws, proj, user, state=st_cancelled, parent=root)
        _estimate(ws, proj, root, 42.0)

        result = bulk_estimates(user, ws.slug, [root.id])

        self.assertEqual(result[str(root.id)], 42.0)


# ---------------------------------------------------------------------------
# parent_issue_ids() batch helper
# ---------------------------------------------------------------------------

class TestParentIssueIdsBatch(TransactionTestCase):
    def test_batch_matches_individual_is_parent_calls(self):
        ws = _ws()
        proj = _project(ws)
        user = _user()
        _pmember(ws, proj, user)
        st = _state(ws, proj, "started")
        root = _issue(ws, proj, user, state=st)
        _issue(ws, proj, user, state=st, parent=root)
        leaf = _issue(ws, proj, user, state=st)

        result = parent_issue_ids([root.id, leaf.id])

        self.assertEqual(result, {root.id})
        self.assertTrue(is_parent(root.id))
        self.assertFalse(is_parent(leaf.id))

    def test_empty_input_returns_empty_set(self):
        self.assertEqual(parent_issue_ids([]), set())
