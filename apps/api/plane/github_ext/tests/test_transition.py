# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P2 — status-automation DB tests. The headline test is the trap #4 gate:
# a transition must fire IssueActivity (proved by spying issue_activity.delay
# in the core view) — i.e. it goes through the service-token API path, not a
# raw issue.save(). All payloads are inline mocks; no real GitHub creds.

from unittest import mock

from django.test import TransactionTestCase

from plane.github_ext.tests.test_links import _installation, _issue, _map
from plane.github_ext.tests.test_webhook import _bind_github_workspace, _project, _workspace

# The core view fires this on a successful PATCH — spying it proves the
# service-token path fired side-effects (trap #4), without needing eager Celery.
_ACTIVITY_PATCH = "plane.api.views.issue.issue_activity.delay"


def _state(ws, project, name, group):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws, project=project, name=name, color="#fff", group=group
    )


def _pr_payload(
    installation_id,
    repo,
    number,
    action,
    merged=False,
    head_ref="",
    title="",
    body="",
    sender_login="a-dev",
):
    return {
        "action": action,
        "installation": {"id": int(installation_id)},
        "repository": {"full_name": repo},
        "sender": {"login": sender_login},
        "pull_request": {
            "number": number,
            "merged": merged,
            "head": {"ref": head_ref},
            "title": title,
            "body": body,
            "html_url": f"https://github.com/{repo}/pull/{number}",
        },
    }


class PrTransitionTests(TransactionTestCase):
    def setUp(self):
        from plane.db.models import ProjectMember, WorkspaceMember
        from plane.github_ext.bgtasks.transition_task import process_pr_transition

        self.process = process_pr_transition
        self.ws = _workspace()
        # Bot + service APIToken live on the github WorkspaceIntegration.
        self.wi = _bind_github_workspace(self.ws)
        self.bot = self.wi.actor
        # The service-token PATCH runs as the bot — it must be a workspace +
        # project member for the core issue endpoint to authorize the update.
        WorkspaceMember.objects.get_or_create(
            workspace=self.ws, member=self.bot, defaults={"role": 20}
        )
        self.installation = _installation(self.ws)
        self.project = _project(self.ws, name="Plane Core", identifier="PROJ")
        ProjectMember.objects.get_or_create(
            workspace=self.ws, project=self.project, member=self.bot, defaults={"role": 20}
        )
        self.repo = "The1Studio/plane"
        _map(self.installation, self.repo, self.project)

        self.backlog = _state(self.ws, self.project, "Backlog", "backlog")
        self.in_progress = _state(self.ws, self.project, "In Progress", "started")
        self.in_review = _state(self.ws, self.project, "In Review", "started")
        self.done = _state(self.ws, self.project, "Done", "completed")

        self.issue = _issue(self.ws, self.project, seq=3)
        self.issue.state = self.backlog
        self.issue.save(update_fields=["state"])
        self.identifier = f"PROJ-{self.issue.sequence_id}"

    def _run(self, **kw):
        payload = _pr_payload(self.installation.installation_id, self.repo, **kw)
        self.process(payload=payload)
        self.issue.refresh_from_db()

    # -- trap #4 gate: opened → In Progress AND activity fired ----------------

    def test_pr_opened_moves_to_in_progress_and_fires_activity(self):
        with mock.patch(_ACTIVITY_PATCH) as mock_activity:
            self._run(number=7, action="opened", head_ref=f"{self.identifier}-x")
        self.assertEqual(self.issue.state_id, self.in_progress.id)
        self.assertTrue(mock_activity.called, "trap #4: issue_activity.delay must fire")

    def test_pr_ready_for_review_moves_to_in_review(self):
        self._run(number=7, action="ready_for_review", head_ref=f"{self.identifier}-x")
        self.assertEqual(self.issue.state_id, self.in_review.id)

    def test_pr_merged_with_closing_word_moves_to_done(self):
        self._run(number=7, action="closed", merged=True, title=f"Fixes {self.identifier}")
        self.assertEqual(self.issue.state_id, self.done.id)

    def test_pr_closed_unmerged_no_transition(self):
        self._run(number=7, action="closed", merged=False, title=f"Fixes {self.identifier}")
        self.assertEqual(self.issue.state_id, self.backlog.id)

    def test_pr_merged_without_closing_word_not_done(self):
        # Referenced but no closing word → link only, no Done transition.
        self._run(number=7, action="closed", merged=True, title=f"See {self.identifier}")
        self.assertEqual(self.issue.state_id, self.backlog.id)

    # -- loop guard: our own bot's event is dropped ---------------------------

    def test_echo_from_bot_is_dropped(self):
        self.installation.config = {"bot_login": "plane-github-bot"}
        self.installation.save(update_fields=["config"])
        with mock.patch(_ACTIVITY_PATCH) as mock_activity:
            self._run(
                number=7,
                action="opened",
                head_ref=f"{self.identifier}-x",
                sender_login="plane-github-bot",
            )
        self.assertEqual(self.issue.state_id, self.backlog.id)
        self.assertFalse(mock_activity.called)

    # -- missing target state → skip, no exception ----------------------------

    def test_missing_completed_state_skips_cleanly(self):
        # A project with no completed-group state: merged+closing word must not
        # raise, and must not change the issue.
        proj2 = _project(self.ws, name="No Done", identifier="ND")
        _state(self.ws, proj2, "Backlog", "backlog")
        from plane.db.models import ProjectMember

        ProjectMember.objects.get_or_create(
            workspace=self.ws, project=proj2, member=self.bot, defaults={"role": 20}
        )
        from plane.github_ext.models import RepoProjectMap

        repo2 = "The1Studio/no-done"
        RepoProjectMap.objects.create(
            installation=self.installation, repo_full_name=repo2, project=proj2
        )
        issue2 = _issue(self.ws, proj2, seq=1)
        issue2.refresh_from_db()
        state_before = issue2.state_id  # Issue.save() auto-assigns a default state

        payload = _pr_payload(
            self.installation.installation_id,
            repo2,
            number=9,
            action="closed",
            merged=True,
            title="Fixes ND-1",
        )
        # Must not raise, and must not move the issue (no completed state exists).
        self.process(payload=payload)
        issue2.refresh_from_db()
        self.assertEqual(issue2.state_id, state_before)
