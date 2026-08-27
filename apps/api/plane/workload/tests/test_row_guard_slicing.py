# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The ROW_GUARD check was two COUNT(*) queries; it is now a slice plus len().
# That is a performance change that must be behaviour-neutral, so these tests
# pin the guard's SEMANTICS rather than its implementation: they would pass
# against either version and fail against a version that gets the boundary
# wrong.
#
# Rationale and the equivalence argument: plane/workload/service.py, the
# "Row guard" comment in compute_workload.

from datetime import date, timedelta
from unittest import mock

from django.test import TransactionTestCase

from plane.db.models import Project, State, User, Workspace, WorkspaceMember
from plane.workload.models import WorkloadEstimate
from plane.workload.service import WorkloadTooLarge, compute_workload


def _uid():
    import uuid

    return uuid.uuid4().hex[:8]


class RowGuardBoundaryTests(TransactionTestCase):
    """The guard fires on total rows across BOTH querysets, not one each."""

    def setUp(self):
        u = _uid()
        self.owner = User.objects.create_user(
            username=f"o_{u}", email=f"o-{u}@test.invalid", password="x"
        )
        self.ws = Workspace.objects.create(name=f"ws {u}", slug=f"ws-{u}", owner=self.owner)
        WorkspaceMember.objects.create(workspace=self.ws, member=self.owner, role=20, is_active=True)
        self.project = Project.objects.create(
            name="p", identifier=f"P{u[:4].upper()}", workspace=self.ws
        )
        self.state = State.objects.create(
            name="Todo", group="unstarted", project=self.project, workspace=self.ws, sequence=1
        )
        self.kw = dict(
            user=self.owner,
            slug=self.ws.slug,
            granularity="week",
            date_from=date(2026, 8, 1),
            date_to=date(2026, 10, 31),
        )

    def _issue(self, seq, target=date(2026, 8, 15), hours=None):
        from plane.db.models import Issue

        issue = Issue.objects.create(
            name=f"i{seq}",
            project=self.project,
            workspace=self.ws,
            state=self.state,
            sequence_id=seq,
            target_date=target,
        )
        if hours is not None:
            WorkloadEstimate.objects.create(
                issue=issue, workspace=self.ws, project=self.project, hours=hours
            )
        return issue

    def test_under_the_guard_returns_normally(self):
        for i in range(1, 4):
            self._issue(i, hours=2.0)
        self.assertIn("rows", compute_workload(**self.kw))

    def test_guard_counts_estimated_and_unestimated_TOGETHER(self):
        """The load-bearing case: one budget across both querysets.

        Two estimated + two unestimated against a guard of 3 must raise. A
        version that gave each queryset its own ceiling of 3 would pass this
        with 2 and 2, which is the bug the shared budget exists to prevent.
        """
        for i in range(1, 3):
            self._issue(i, hours=2.0)
        for i in range(3, 5):
            self._issue(i)  # unestimated
        with mock.patch("plane.workload.service.ROW_GUARD", 3):
            with self.assertRaises(WorkloadTooLarge):
                compute_workload(**self.kw)

    def test_exactly_at_the_guard_does_not_raise(self):
        """Boundary: the guard is `> ROW_GUARD`, not `>=`.

        Off-by-one here is exactly what a slice-and-len rewrite risks, which is
        why the equal case is pinned separately from the over case.
        """
        for i in range(1, 4):
            self._issue(i, hours=2.0)
        with mock.patch("plane.workload.service.ROW_GUARD", 3):
            self.assertIn("rows", compute_workload(**self.kw))

    def test_one_over_the_guard_raises(self):
        for i in range(1, 5):
            self._issue(i, hours=2.0)
        with mock.patch("plane.workload.service.ROW_GUARD", 3):
            with self.assertRaises(WorkloadTooLarge):
                compute_workload(**self.kw)

    def test_unestimated_alone_can_trip_the_guard(self):
        for i in range(1, 5):
            self._issue(i)
        with mock.patch("plane.workload.service.ROW_GUARD", 3):
            with self.assertRaises(WorkloadTooLarge):
                compute_workload(**self.kw)
