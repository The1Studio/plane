# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1 — dev-workflow link DB tests: parse identifiers from push/PR payloads,
# resolve the Issue strictly within the repo's mapped project, write
# WorkItemGithubLink + mirror IssueLink, and stay idempotent on redelivery.
# All payloads are inline mocks — no real GitHub credentials.

import uuid

from django.test import TransactionTestCase

# Reuse the P0 test helpers (workspace/project/github-workspace bind).
from plane.github_ext.tests.test_webhook import (
    _bind_github_workspace,
    _project,
    _user,
    _workspace,
)


def _installation(ws, installation_id="555", account_login="the1studio"):
    from plane.github_ext.models import GithubInstallation

    return GithubInstallation.objects.create(
        installation_id=installation_id, account_login=account_login, workspace=ws
    )


def _map(installation, repo_full_name, project):
    from plane.github_ext.models import RepoProjectMap

    return RepoProjectMap.objects.create(
        installation=installation, repo_full_name=repo_full_name, project=project
    )


def _issue(ws, project, seq):
    from plane.db.models import Issue

    issue = Issue.objects.create(
        workspace=ws,
        project=project,
        name=f"i-{uuid.uuid4().hex[:6]}",
        created_by=ws.owner,
        sequence_id=seq,
    )
    issue.refresh_from_db()
    return issue


def _push_payload(installation_id, repo_full_name, ref=None, commits=None):
    return {
        "installation": {"id": int(installation_id)},
        "repository": {"full_name": repo_full_name},
        "ref": ref,
        "commits": commits or [],
    }


def _pr_payload(installation_id, repo_full_name, number, head_ref="", title="", body=""):
    return {
        "installation": {"id": int(installation_id)},
        "repository": {"full_name": repo_full_name},
        "pull_request": {
            "number": number,
            "head": {"ref": head_ref},
            "title": title,
            "body": body,
            "html_url": f"https://github.com/{repo_full_name}/pull/{number}",
        },
    }


class DevWorkflowLinkTests(TransactionTestCase):
    def setUp(self):
        from plane.github_ext.bgtasks.link_task import process_refs

        self.process_refs = process_refs
        self.ws = _workspace()
        _bind_github_workspace(self.ws)
        self.installation = _installation(self.ws)
        self.project = _project(self.ws, name="Plane Core", identifier="PROJ")
        self.repo = "The1Studio/plane"
        _map(self.installation, self.repo, self.project)
        self.issue = _issue(self.ws, self.project, seq=3)
        self.identifier = f"PROJ-{self.issue.sequence_id}"

    # -- branch push → link + mirror ----------------------------------------

    def test_push_branch_creates_link_and_issuelink_mirror(self):
        from plane.db.models import IssueLink
        from plane.github_ext.models import WorkItemGithubLink

        branch = f"{self.identifier}-add-widget"
        payload = _push_payload(
            self.installation.installation_id, self.repo, ref=f"refs/heads/{branch}"
        )
        self.process_refs("push", payload=payload)

        link = WorkItemGithubLink.objects.get(issue=self.issue, link_type="branch")
        self.assertEqual(link.external_id, branch)
        self.assertEqual(link.project_id, self.project.id)
        # Mirrored into the core Links panel on the same URL.
        self.assertTrue(IssueLink.objects.filter(issue_id=self.issue.id, url=link.url).exists())

    # -- redelivery idempotency ---------------------------------------------

    def test_redelivery_creates_no_duplicate(self):
        from plane.db.models import IssueLink
        from plane.github_ext.models import WorkItemGithubLink

        branch = f"{self.identifier}-x"
        payload = _push_payload(
            self.installation.installation_id, self.repo, ref=f"refs/heads/{branch}"
        )
        self.process_refs("push", payload=payload)
        self.process_refs("push", payload=payload)

        self.assertEqual(
            WorkItemGithubLink.objects.filter(issue=self.issue, link_type="branch").count(), 1
        )
        self.assertEqual(IssueLink.objects.filter(issue_id=self.issue.id).count(), 1)

    # -- unmapped repo → dropped --------------------------------------------

    def test_unmapped_repo_creates_no_link(self):
        from plane.github_ext.models import WorkItemGithubLink

        payload = _push_payload(
            self.installation.installation_id,
            "The1Studio/not-mapped",
            ref=f"refs/heads/{self.identifier}-y",
        )
        self.process_refs("push", payload=payload)
        self.assertFalse(WorkItemGithubLink.objects.exists())

    # -- wrong project prefix → skipped (never cross-mapped) ----------------

    def test_identifier_for_other_project_is_skipped(self):
        from plane.github_ext.models import WorkItemGithubLink

        # Repo maps to PROJ; branch references ABC-3 → must not resolve into
        # PROJ's sequence_id space.
        payload = _push_payload(
            self.installation.installation_id, self.repo, ref="refs/heads/ABC-3-foo"
        )
        self.process_refs("push", payload=payload)
        self.assertFalse(WorkItemGithubLink.objects.exists())

    # -- PR title closing word → flag recorded on metadata ------------------

    def test_pr_title_closing_word_recorded(self):
        from plane.github_ext.models import WorkItemGithubLink

        payload = _pr_payload(
            self.installation.installation_id,
            self.repo,
            number=42,
            title=f"Fixes {self.identifier}",
        )
        self.process_refs("pull_request", payload=payload)

        link = WorkItemGithubLink.objects.get(issue=self.issue, link_type="pr")
        self.assertEqual(link.external_id, "42")
        self.assertEqual(link.metadata.get("closing_word"), "fixes")
