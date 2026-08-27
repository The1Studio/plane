# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Version-bump COVERAGE. This is the load-bearing test of the whole feature.
#
# A missed bump does not fail loudly — it serves stale data that looks fresh,
# which is the highest-scored risk in the plan (15). The parameterization below
# is deliberate: a model added to the endpoint's read set but NOT given a
# receiver fails here, rather than shipping and going quiet.

import uuid

from django.db.models.signals import post_delete, post_save
from django.test import TransactionTestCase

from plane.db.models import Issue, IssueAssignee, ProjectMember, State, Workspace
from plane.workload.models import WorkloadEstimate, WorkloadSettings

# Every model whose change can alter a workload response, derived from the 13
# queries compute_workload actually runs (plan.md § query breakdown).
#
# `Project` is deliberately ABSENT: a project rename does not surface in the
# response (tasks[].project_id is a UUID). If that ever changes, this list gains
# a row — and test_every_read_model_has_a_receiver is what will notice.
MODELS_THAT_AFFECT_THE_RESPONSE = [
    Issue,
    IssueAssignee,
    ProjectMember,
    State,
    Workspace,
    WorkloadEstimate,
    WorkloadSettings,
]


def _receivers(signal, sender):
    """Receivers actually registered for (signal, sender)."""
    return [r for r in signal._live_receivers(sender) if r]


class TestReceiverCoverage(TransactionTestCase):
    """Structural: is every model wired at all?

    Runs without touching Redis or building fixtures, so it fails fast and for
    an unambiguous reason.
    """

    def test_every_read_model_has_a_post_save_receiver(self):
        missing = [m.__name__ for m in MODELS_THAT_AFFECT_THE_RESPONSE if not _receivers(post_save, m)]
        self.assertEqual(
            missing,
            [],
            f"No post_save version-bump receiver for: {missing}. "
            "A model read by the workload endpoint with no receiver means edits "
            "to it leave a STALE cached response that looks fresh. Add the "
            "receiver in plane/workload_cache/signals.py — do not remove the "
            "model from this list to make the test pass.",
        )

    def test_every_read_model_except_workspace_has_a_post_delete_receiver(self):
        # Workspace is post_save-only on purpose: a deleted workspace cascades
        # its rows away and nothing can request its cache any more, so there is
        # nothing left to invalidate.
        expected = [m for m in MODELS_THAT_AFFECT_THE_RESPONSE if m is not Workspace]
        missing = [m.__name__ for m in expected if not _receivers(post_delete, m)]
        self.assertEqual(
            missing,
            [],
            f"No post_delete version-bump receiver for: {missing}. "
            "Deleting one of these changes the response exactly as editing it does.",
        )


class TestBumpFires(TransactionTestCase):
    """Behavioural: does a write actually move the version counter?

    Uses a fake client so the assertion is about the receiver firing, not about
    a live Redis being reachable in CI.
    """

    def setUp(self):
        from unittest import mock

        from plane.workload_cache import cache as cache_mod

        self.bumped = []
        self._patch = mock.patch.object(
            cache_mod, "bump_workspace", side_effect=lambda slug: self.bumped.append(slug)
        )
        # signals.py imported bump_workspace by value, so patch it there too.
        from plane.workload_cache import signals as signals_mod

        self._patch2 = mock.patch.object(
            signals_mod, "bump_workspace", side_effect=lambda slug: self.bumped.append(slug)
        )
        self._patch.start()
        self._patch2.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._patch2.stop)

    def _workspace(self):
        from plane.db.models import User

        uid = uuid.uuid4().hex[:8]
        owner = User.objects.create_user(username=f"o_{uid}", email=f"o-{uid}@test.invalid", password="x")
        return Workspace.objects.create(name=f"ws {uid}", slug=f"ws-{uid}", owner=owner), owner

    def test_workspace_save_bumps_its_own_slug(self):
        ws, _ = self._workspace()
        self.assertIn(ws.slug, self.bumped)

    def test_state_save_bumps_the_workspace(self):
        ws, owner = self._workspace()
        from plane.db.models import Project

        project = Project.objects.create(name="p", identifier="P", workspace=ws)
        self.bumped.clear()
        State.objects.create(name="Todo", group="unstarted", project=project, workspace=ws, sequence=1)
        self.assertIn(ws.slug, self.bumped)

    def test_workload_settings_save_bumps_the_workspace(self):
        ws, _ = self._workspace()
        self.bumped.clear()
        WorkloadSettings.objects.create(workspace=ws)
        self.assertIn(ws.slug, self.bumped)
