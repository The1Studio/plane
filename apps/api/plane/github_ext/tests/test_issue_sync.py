# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P3 — bidirectional issue/comment sync tests.
#
# Two of these are MERGE GATES (phase-P3.md risk table):
#   * `test_inbound_issue_opened_creates_work_item_and_writes_activity`
#     — trap #4 (15/25): the inbound write must go through the service-token
#     internal API, proven by a REAL `IssueActivity` row existing afterwards.
#     `issue_activity.delay` is replaced with an inline runner so the row is
#     actually written in-test (a plain spy would only prove the call, not the
#     side effect).
#   * `test_echo_guard_drops_plane_originated_reflection`
#     — echo loop (20/25): a GitHub event replaying content we ourselves
#     pushed must be dropped with no second write.
#
# No real GitHub credentials anywhere: the App private key is generated
# in-test, and every network call is mocked.

import copy
import json
from unittest import mock

from django.test import TransactionTestCase

from plane.github_ext.tests.test_links import _installation, _issue, _map
from plane.github_ext.tests.test_webhook import (
    _bind_github_workspace,
    _load_fixture,
    _project,
    _workspace,
)

_ACTIVITY_DELAY = "plane.api.views.issue.issue_activity.delay"
_MODEL_ACTIVITY_DELAY = "plane.api.views.issue.model_activity.delay"


def _run_activity_inline(**kwargs):
    """Execute the real `issue_activity` task body synchronously.

    This is what makes the trap #4 gate assert a side EFFECT (an IssueActivity
    row) rather than merely that `.delay` was called.
    """
    from plane.bgtasks.issue_activities_task import issue_activity

    return issue_activity(**kwargs)


def _state(ws, project, name, group, sequence=1000):
    from plane.db.models import State

    return State.objects.create(
        workspace=ws, project=project, name=name, color="#fff", group=group, sequence=sequence
    )


def _rsa_private_key_pem():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class IssueSyncTestBase(TransactionTestCase):
    def setUp(self):
        from plane.db.models import ProjectMember, WorkspaceMember
        from plane.github_ext.bgtasks.issue_sync_task import process_issue_sync

        self.process = process_issue_sync
        self.ws = _workspace()
        self.wi = _bind_github_workspace(self.ws)
        self.bot = self.wi.actor
        WorkspaceMember.objects.get_or_create(workspace=self.ws, member=self.bot, defaults={"role": 20})

        self.installation = _installation(self.ws)
        self.project = _project(self.ws, name="Plane Core", identifier="PROJ")
        ProjectMember.objects.get_or_create(
            workspace=self.ws, project=self.project, member=self.bot, defaults={"role": 20}
        )
        self.repo = "The1Studio/plane"
        _map(self.installation, self.repo, self.project)

        _state(self.ws, self.project, "Backlog", "backlog", sequence=1000)
        self.in_progress = _state(self.ws, self.project, "In Progress", "started", sequence=2000)
        self.done = _state(self.ws, self.project, "Done", "completed", sequence=3000)

        # Every test writes through the core API views; run the activity task
        # inline (so rows exist) and stub the webhook fan-out.
        activity = mock.patch(_ACTIVITY_DELAY, side_effect=_run_activity_inline)
        self.mock_activity = activity.start()
        self.addCleanup(activity.stop)
        model_activity = mock.patch(_MODEL_ACTIVITY_DELAY)
        self.mock_model_activity = model_activity.start()
        self.addCleanup(model_activity.stop)

    # -- payload builders ---------------------------------------------------

    def _issue_payload(self, **overrides):
        payload = copy.deepcopy(_load_fixture("issues_opened.json"))
        payload["installation"]["id"] = int(self.installation.installation_id)
        payload["repository"]["full_name"] = self.repo
        issue_overrides = overrides.pop("issue", {})
        payload.update(overrides)
        payload["issue"].update(issue_overrides)
        return payload

    def _comment_payload(self, **overrides):
        payload = copy.deepcopy(_load_fixture("issue_comment_created.json"))
        payload["installation"]["id"] = int(self.installation.installation_id)
        payload["repository"]["full_name"] = self.repo
        issue_overrides = overrides.pop("issue", {})
        comment_overrides = overrides.pop("comment", {})
        payload.update(overrides)
        payload["issue"].update(issue_overrides)
        payload["comment"].update(comment_overrides)
        return payload

    def _external_id(self, number=42):
        return f"{self.repo}#{number}"


class InboundIssueSyncTests(IssueSyncTestBase):
    # -- MERGE GATE: trap #4 — service-token API path fired IssueActivity ----

    def test_inbound_issue_opened_creates_work_item_and_writes_activity(self):
        from plane.db.models import Issue, IssueActivity, IssueLink
        from plane.github_ext.models import WorkItemGithubLink

        self.process("issues", payload=self._issue_payload())

        issue = Issue.objects.get(project=self.project, external_id=self._external_id())
        self.assertEqual(issue.external_source, "github")
        self.assertEqual(issue.name, "Crash when opening the workload matrix")
        self.assertIn("Steps to reproduce", issue.description_html)

        # Trap #4 gate: a real IssueActivity row exists, which only happens
        # because the write went through the core API view (a raw ORM create
        # would have produced the Issue row and NOTHING else).
        self.assertTrue(
            IssueActivity.objects.filter(issue_id=issue.id).exists(),
            "trap #4: inbound sync must produce an IssueActivity row",
        )

        # Mirror bookkeeping + provenance stamp.
        link = WorkItemGithubLink.objects.get(issue=issue, link_type="issue")
        self.assertEqual(link.external_id, self._external_id())
        self.assertEqual(link.metadata["source"], "github")
        self.assertEqual(link.metadata["repo"], self.repo)
        self.assertIn("synced_at", link.metadata)
        self.assertIn("github_hash", link.metadata)
        # Display mirror in the core Links panel (P1 precedent).
        self.assertTrue(IssueLink.objects.filter(issue_id=issue.id, url=link.url).exists())

    def test_redelivery_creates_no_duplicate_work_item(self):
        from plane.db.models import Issue

        payload = self._issue_payload()
        self.process("issues", payload=payload)
        self.process("issues", payload=payload)

        self.assertEqual(Issue.objects.filter(project=self.project, external_id=self._external_id()).count(), 1)

    def test_inbound_edit_updates_existing_work_item(self):
        from plane.db.models import Issue

        self.process("issues", payload=self._issue_payload())
        self.process(
            "issues",
            payload=self._issue_payload(action="edited", issue={"title": "Crash on month view"}),
        )

        issue = Issue.objects.get(project=self.project, external_id=self._external_id())
        self.assertEqual(issue.name, "Crash on month view")
        self.assertEqual(Issue.objects.filter(project=self.project).count(), 1)

    def test_inbound_closed_moves_to_completed_state(self):
        from plane.db.models import Issue

        self.process("issues", payload=self._issue_payload(action="closed", issue={"state": "closed"}))

        issue = Issue.objects.get(project=self.project, external_id=self._external_id())
        self.assertEqual(issue.state_id, self.done.id)

    def test_long_title_is_truncated_not_dropped(self):
        from plane.db.models import Issue

        self.process("issues", payload=self._issue_payload(issue={"title": "x" * 400}))

        issue = Issue.objects.get(project=self.project, external_id=self._external_id())
        self.assertEqual(len(issue.name), 255)

    # -- drop paths ----------------------------------------------------------

    def test_event_from_our_own_bot_is_dropped(self):
        from plane.db.models import Issue

        self.installation.config = {"bot_login": "plane-github-bot"}
        self.installation.save(update_fields=["config"])

        self.process("issues", payload=self._issue_payload(sender={"login": "plane-github-bot"}))

        self.assertFalse(Issue.objects.filter(project=self.project).exists())

    def test_unmapped_repo_is_dropped(self):
        from plane.db.models import Issue

        payload = self._issue_payload()
        payload["repository"]["full_name"] = "The1Studio/not-mapped"

        self.process("issues", payload=payload)

        self.assertFalse(Issue.objects.filter(project=self.project).exists())

    def test_pull_request_shaped_issue_event_is_ignored(self):
        from plane.db.models import Issue

        payload = self._issue_payload()
        payload["issue"]["pull_request"] = {"url": "https://api.github.com/repos/x/y/pulls/42"}

        self.process("issues", payload=payload)

        self.assertFalse(Issue.objects.filter(project=self.project).exists())

    def test_unhandled_action_is_ignored(self):
        from plane.db.models import Issue

        self.process("issues", payload=self._issue_payload(action="deleted"))

        self.assertFalse(Issue.objects.filter(project=self.project).exists())


class EchoGuardTests(IssueSyncTestBase):
    # -- MERGE GATE: echo loop -----------------------------------------------

    def test_echo_guard_drops_plane_originated_reflection(self):
        """A GitHub event replaying content Plane itself pushed is dropped."""
        from plane.db.models import Issue, IssueActivity
        from plane.github_ext.services.issue_sync import github_content_hash, stamp_provenance

        # 1. Establish the mirror from an inbound sync.
        self.process("issues", payload=self._issue_payload())
        issue = Issue.objects.get(project=self.project, external_id=self._external_id())

        from plane.github_ext.models import WorkItemGithubLink

        link = WorkItemGithubLink.objects.get(issue=issue, link_type="issue")

        # 2. Simulate an OUTBOUND push: Plane became the origin of the current
        #    content, recorded with the GitHub-side hash we sent.
        pushed_title = "Title written by Plane"
        pushed_body = "Body written by Plane"
        stamp_provenance(
            link,
            source="plane",
            external_id=self._external_id(),
            github_hash=github_content_hash(pushed_title, pushed_body),
            plane_hash="irrelevant-for-this-direction",
            extra={"repo": self.repo},
        )

        activity_before = IssueActivity.objects.filter(issue_id=issue.id).count()
        updated_before = Issue.objects.get(pk=issue.id).updated_at

        # 3. GitHub echoes that exact content back at us.
        self.process(
            "issues",
            payload=self._issue_payload(
                action="edited", issue={"title": pushed_title, "body": pushed_body}
            ),
        )

        issue.refresh_from_db()
        # Dropped: content untouched, no second write, no new activity row.
        self.assertEqual(issue.name, "Crash when opening the workload matrix")
        self.assertEqual(IssueActivity.objects.filter(issue_id=issue.id).count(), activity_before)
        self.assertEqual(Issue.objects.get(pk=issue.id).updated_at, updated_before)
        self.assertEqual(Issue.objects.filter(project=self.project).count(), 1)

    def test_genuine_github_edit_after_outbound_push_is_not_dropped(self):
        """The guard must be precise: same `source`, DIFFERENT content is a
        real human edit and must still apply (a bare source== rule would
        wrongly swallow it)."""
        from plane.db.models import Issue
        from plane.github_ext.models import WorkItemGithubLink
        from plane.github_ext.services.issue_sync import github_content_hash, stamp_provenance

        self.process("issues", payload=self._issue_payload())
        issue = Issue.objects.get(project=self.project, external_id=self._external_id())
        link = WorkItemGithubLink.objects.get(issue=issue, link_type="issue")

        stamp_provenance(
            link,
            source="plane",
            external_id=self._external_id(),
            github_hash=github_content_hash("Title written by Plane", "Body written by Plane"),
            extra={"repo": self.repo},
        )

        self.process(
            "issues",
            payload=self._issue_payload(
                action="edited", issue={"title": "A human edited this on GitHub"}
            ),
        )

        issue.refresh_from_db()
        self.assertEqual(issue.name, "A human edited this on GitHub")

    def test_is_reflection_unit_matrix(self):
        from plane.github_ext.services.issue_sync import is_reflection

        stamp = {"source": "plane", "github_hash": "aaa", "plane_hash": "bbb"}
        # Writing to Plane content that Plane itself originated -> reflection.
        self.assertTrue(is_reflection(stamp, "plane", "aaa"))
        # Same origin side but different content -> a real edit.
        self.assertFalse(is_reflection(stamp, "plane", "zzz"))
        # Other direction: last sync came from Plane, so pushing to GitHub is
        # legitimate propagation, not a reflection.
        self.assertFalse(is_reflection(stamp, "github", "bbb"))
        # No stamp at all -> never a reflection.
        self.assertFalse(is_reflection({}, "plane", "aaa"))
        self.assertFalse(is_reflection(None, "plane", "aaa"))


class CommentSyncTests(IssueSyncTestBase):
    def _mirrored_issue(self):
        from plane.db.models import Issue

        self.process("issues", payload=self._issue_payload())
        return Issue.objects.get(project=self.project, external_id=self._external_id())

    def test_comment_roundtrip_creates_plane_comment_with_no_reflection_back(self):
        from plane.db.models import IssueComment

        issue = self._mirrored_issue()

        self.process("issue_comment", payload=self._comment_payload())

        comment = IssueComment.objects.get(issue_id=issue.id, external_id="9900110022")
        self.assertEqual(comment.external_source, "github")
        self.assertIn("Reproduced on staging", comment.comment_html)

        # No reflection back: the outbound path refuses a GitHub-originated
        # comment, and makes no network call at all.
        from plane.github_ext.bgtasks.issue_sync_task import push_comment

        with mock.patch("requests.post") as mock_post:
            result = push_comment(str(comment.id))

        self.assertIsNone(result)
        mock_post.assert_not_called()

    def test_comment_redelivery_creates_no_duplicate(self):
        from plane.db.models import IssueComment

        issue = self._mirrored_issue()
        payload = self._comment_payload()

        self.process("issue_comment", payload=payload)
        self.process("issue_comment", payload=payload)

        self.assertEqual(IssueComment.objects.filter(issue_id=issue.id, external_id="9900110022").count(), 1)

    def test_comment_on_unmirrored_issue_is_skipped(self):
        from plane.db.models import IssueComment

        self.process("issue_comment", payload=self._comment_payload(issue={"number": 999}))

        self.assertFalse(IssueComment.objects.filter(external_source="github").exists())

    def test_pull_request_comment_is_ignored(self):
        from plane.db.models import IssueComment

        self._mirrored_issue()
        payload = self._comment_payload()
        payload["issue"]["pull_request"] = {"url": "https://api.github.com/repos/x/y/pulls/42"}

        self.process("issue_comment", payload=payload)

        self.assertFalse(IssueComment.objects.filter(external_source="github").exists())

    def test_plane_authored_comment_is_eligible_for_outbound(self):
        from plane.db.models import IssueComment
        from plane.github_ext.services.issue_sync import should_push_comment

        issue = self._mirrored_issue()
        comment = IssueComment.objects.create(
            workspace=self.ws,
            project=self.project,
            issue=issue,
            actor=self.ws.owner,
            comment_html="<p>Written in Plane</p>",
        )
        self.assertTrue(should_push_comment(comment))


class OutboundPushTests(IssueSyncTestBase):
    APP_ID = "123456"

    def setUp(self):
        super().setUp()
        import os

        env = mock.patch.dict(
            os.environ,
            {"GITHUB_APP_ID": self.APP_ID, "GITHUB_APP_PRIVATE_KEY": _rsa_private_key_pem()},
        )
        env.start()
        self.addCleanup(env.stop)

    def test_outbound_uses_fresh_installation_token_and_stamps_provenance(self):
        from plane.db.models import Issue
        from plane.github_ext.bgtasks.issue_sync_task import push_work_item
        from plane.github_ext.models import WorkItemGithubLink

        # Mirror exists (created inbound), then a human edits it in Plane.
        self.process("issues", payload=self._issue_payload())
        issue = Issue.objects.get(project=self.project, external_id=self._external_id())
        issue.name = "Edited in Plane"
        issue.save(update_fields=["name"])

        token = "ghs_fresh_installation_token"
        with mock.patch("requests.post", return_value=_FakeResponse(201, {"token": token})) as mock_post:
            with mock.patch("requests.patch", return_value=_FakeResponse(200)) as mock_patch:
                status_code = push_work_item(str(issue.id))

        self.assertEqual(status_code, 200)

        # A FRESH installation token was minted for this call, using an App
        # JWT signed with the App's private key.
        mock_post.assert_called_once()
        token_url = mock_post.call_args.args[0]
        self.assertEqual(
            token_url,
            f"https://api.github.com/app/installations/{self.installation.installation_id}/access_tokens",
        )
        assertion = mock_post.call_args.kwargs["headers"]["Authorization"].split(" ", 1)[1]

        import jwt

        claims = jwt.decode(assertion, options={"verify_signature": False})
        self.assertEqual(claims["iss"], self.APP_ID)
        self.assertLessEqual(claims["exp"] - claims["iat"], 600)

        # ...and the REST call carried that token, not the App JWT.
        mock_patch.assert_called_once()
        self.assertEqual(mock_patch.call_args.kwargs["headers"]["Authorization"], f"Bearer {token}")
        self.assertEqual(mock_patch.call_args.kwargs["json"]["title"], "Edited in Plane")

        # Provenance stamped: Plane is now the origin of the mirrored content.
        link = WorkItemGithubLink.objects.get(issue=issue, link_type="issue")
        self.assertEqual(link.metadata["source"], "plane")
        self.assertIn("synced_at", link.metadata)

        # The installation token is never persisted (plan §7) — not in the
        # provenance stamp, and not anywhere else the sync writes.
        self.assertNotIn(token, json.dumps(link.metadata))
        self.assertNotIn(token, link.url)
        for row in WorkItemGithubLink.objects.all():
            self.assertNotIn(token, json.dumps(row.metadata))

    def test_outbound_drops_reflection_of_inbound_content(self):
        from plane.db.models import Issue
        from plane.github_ext.bgtasks.issue_sync_task import push_work_item

        # Straight after an inbound sync the Plane content IS the GitHub
        # content — pushing it back would start the loop.
        self.process("issues", payload=self._issue_payload())
        issue = Issue.objects.get(project=self.project, external_id=self._external_id())

        with mock.patch("requests.post") as mock_post:
            with mock.patch("requests.patch") as mock_patch:
                result = push_work_item(str(issue.id))

        self.assertIsNone(result)
        mock_post.assert_not_called()
        mock_patch.assert_not_called()

    def test_outbound_skips_unmirrored_work_item(self):
        from plane.github_ext.bgtasks.issue_sync_task import push_work_item

        issue = _issue(self.ws, self.project, seq=99)

        with mock.patch("requests.post") as mock_post:
            result = push_work_item(str(issue.id))

        self.assertIsNone(result)
        mock_post.assert_not_called()


class DormantModelIsolationTests(TransactionTestCase):
    """phase-P3.md gate: P3 must add no core/dormant model column.

    The `makemigrations --check --dry-run` half of this gate cannot run inside
    pytest — `pytest.ini` passes `--nomigrations`, which stubs out every app's
    migration module, so `makemigrations` would report the entire schema as
    unmigrated. It runs as a separate `manage.py` invocation (the same one
    `company-main-ci.yml` gates on).
    """

    def test_github_ext_migration_set_is_unchanged(self):
        from pathlib import Path

        import plane.github_ext

        migrations = sorted(
            p.name
            for p in (Path(plane.github_ext.__file__).parent / "migrations").glob("0*.py")
        )
        # P3 reuses existing tables (see services/issue_sync.py memo) — it must
        # not have introduced a third migration.
        self.assertEqual(
            migrations,
            ["0001_initial.py", "0002_statetransitionconfig_workspace_scope.py"],
        )

    def test_dormant_sync_models_are_untouched(self):
        from plane.db.models import GithubCommentSync, GithubIssueSync

        # P3 deliberately does NOT write these (see services/issue_sync.py
        # decision memo): they have no JSON column for the provenance stamp,
        # and populating them would need a duplicate repo->project chain.
        self.assertEqual(GithubIssueSync.objects.count(), 0)
        self.assertEqual(GithubCommentSync.objects.count(), 0)
        for model in (GithubIssueSync, GithubCommentSync):
            field_names = {f.name for f in model._meta.get_fields()}
            self.assertNotIn("metadata", field_names)
            self.assertNotIn("provenance", field_names)
