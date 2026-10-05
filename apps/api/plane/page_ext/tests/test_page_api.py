# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# HTTP-level tests (real Postgres, real APIToken auth via X-Api-Key — never
# force_authenticate, so a regression that drops APIKeyAuthentication fails
# with 401 instead of a false green) for the public-API project-page endpoints.
#
# The headline test is PatchKeepsBinaryHtmlConsistentTests: Plane's live
# (Hocuspocus/Yjs) server treats Page.description_binary as the source of truth,
# so a PATCH that writes only description_html leaves a stale binary that the
# next page-open reloads — silently undoing the edit. That test is the one
# that must go RED against an html-only writer.
#
# page_transaction is a Celery task and plane/settings/test.py sets no eager
# mode, so .delay would try to reach a broker: it is patched, and the
# assertions check it was called with the old/new html. The fork's ai_ext
# post_save signal on Page enqueues an embedding task on commit (apply_async ->
# broker); both its tasks are patched for the same reason, and one test asserts
# the embedding is re-queued with the NEW text. The API request-logger
# middleware also dispatches a Celery task per request; it is patched to keep
# the output free of swallowed broker errors.

import uuid
from unittest.mock import patch

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

ROLE_ADMIN = 20
ROLE_MEMBER = 15
ROLE_GUEST = 5

_HEADER_ROW = "<tr><th><p>Item</p></th><th><p>Status</p></th></tr>"


def _table(status):
    return f"<table><tbody>{_HEADER_ROW}<tr><td><p>Splash</p></td><td><p>{status}</p></td></tr></tbody></table>"


OLD_HTML = _table("todo")
NEW_HTML = _table("done")
STALE_BINARY = b"\x01\x02stale-yjs-state-of-the-OLD-table"

TRANSACTION_TASK = "plane.page_ext.service.page_transaction"


# ---------------------------------------------------------------------------
# ORM helpers
# ---------------------------------------------------------------------------


def _user():
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"user_{uid}", email=f"u-{uid}@test.invalid", password="x")


def _ws():
    from plane.db.models import Workspace

    slug = f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=_user())


def _workspace_member(ws, user, role=ROLE_ADMIN):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(workspace=ws, member=user, role=role, is_active=True)


def _project(ws, **extra):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws, name=f"p-{uuid.uuid4().hex[:6]}", identifier=uuid.uuid4().hex[:5].upper(), **extra
    )


def _project_member(project, user, role=ROLE_MEMBER):
    from plane.db.models import ProjectMember

    return ProjectMember.objects.create(project=project, member=user, role=role)


def _page(project, owner, name="Plan", html=OLD_HTML, binary=STALE_BINARY, **extra):
    from plane.db.models import Page, ProjectPage

    page = Page.objects.create(
        workspace=project.workspace,
        name=name,
        owned_by=owner,
        description_html=html,
        description_json={"type": "doc", "content": ["old"]},
        description_binary=binary,
        **extra,
    )
    ProjectPage.objects.create(workspace=project.workspace, project=project, page=page)
    return page


def _client(user):
    from plane.db.models import APIToken

    client = APIClient()
    client.credentials(HTTP_X_API_KEY=APIToken.objects.create(user=user).token)
    return client


def _reload(page):
    from plane.db.models import Page

    return Page.objects.get(pk=page.pk)


class _Scenario(TransactionTestCase):
    """workspace + project; `self.member` is an active Member, `self.owner` owns pages."""

    def setUp(self):
        from plane.ai_ext.bgtasks import embed_task

        for task in (embed_task.embed_entity, embed_task.purge_entity_embeddings):
            patcher = patch.object(task, "apply_async")
            setattr(self, f"mock_{task.name.rsplit('.', 1)[-1]}", patcher.start())
            self.addCleanup(patcher.stop)

        logger_patcher = patch("plane.middleware.logger.process_logs")
        logger_patcher.start()
        self.addCleanup(logger_patcher.stop)

        self.ws = _ws()
        self.project = _project(self.ws)
        self.owner = _user()
        self.member = _user()
        for user in (self.owner, self.member):
            _workspace_member(self.ws, user, ROLE_MEMBER)
            _project_member(self.project, user, ROLE_MEMBER)
        self.client_member = _client(self.member)
        self.client_owner = _client(self.owner)

    def list_url(self, project=None, slug=None):
        return f"/api/v1/workspaces/{slug or self.ws.slug}/projects/{(project or self.project).id}/pages/"

    def page_url(self, page, project=None, slug=None):
        return f"{self.list_url(project, slug)}{page.id}/"


# ---------------------------------------------------------------------------
# GET list / retrieve
# ---------------------------------------------------------------------------


class ListPagesTests(_Scenario):
    def test_lists_public_pages_and_hides_other_users_private_pages(self):
        public = _page(self.project, self.owner, name="Public")
        private = _page(self.project, self.owner, name="Private", access=1)
        own_private = _page(self.project, self.member, name="Mine", access=1)

        response = self.client_member.get(self.list_url())

        self.assertEqual(response.status_code, 200)
        by_id = {row["id"]: row for row in response.json()}
        self.assertIn(str(public.id), by_id)
        self.assertIn(str(own_private.id), by_id)
        self.assertNotIn(str(private.id), by_id)

    def test_row_shape_has_metadata_and_no_body(self):
        page = _page(self.project, self.owner, name="Plan", is_locked=True, archived_at=timezone.now().date())

        row = self.client_member.get(self.list_url()).json()[0]

        for key in ("id", "name", "access", "owned_by", "parent", "is_locked", "is_archived", "updated_at"):
            self.assertIn(key, row)
        self.assertEqual(row["id"], str(page.id))
        self.assertEqual(row["owned_by"], str(self.owner.id))
        self.assertTrue(row["is_locked"])
        self.assertTrue(row["is_archived"])
        self.assertNotIn("description_html", row)

    def test_does_not_list_pages_of_another_project(self):
        other = _project(self.ws)
        _project_member(other, self.owner, ROLE_MEMBER)
        _page(other, self.owner, name="Elsewhere")

        self.assertEqual(self.client_member.get(self.list_url()).json(), [])

    def test_guest_sees_only_own_pages_unless_project_allows_all(self):
        guest = _user()
        _workspace_member(self.ws, guest, ROLE_GUEST)
        _project_member(self.project, guest, ROLE_GUEST)
        _page(self.project, self.owner, name="Not theirs")
        mine = _page(self.project, guest, name="Theirs")

        rows = _client(guest).get(self.list_url()).json()

        self.assertEqual([row["id"] for row in rows], [str(mine.id)])

    def test_non_project_member_is_refused_even_as_workspace_admin(self):
        admin = _user()
        _workspace_member(self.ws, admin, ROLE_ADMIN)

        self.assertEqual(_client(admin).get(self.list_url()).status_code, 403)

    def test_unauthenticated_is_401(self):
        self.assertEqual(APIClient().get(self.list_url()).status_code, 401)

    def test_slug_that_does_not_own_the_project_is_404(self):
        other_ws = _ws()
        _workspace_member(other_ws, self.member, ROLE_MEMBER)

        response = self.client_member.get(self.list_url(slug=other_ws.slug))

        self.assertIn(response.status_code, (403, 404))


class RetrievePageTests(_Scenario):
    def test_returns_html_and_plain_text(self):
        page = _page(self.project, self.owner, html="<p>Hello <strong>world</strong></p>")

        response = self.client_member.get(self.page_url(page))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["description_html"], "<p>Hello <strong>world</strong></p>")
        self.assertEqual(body["description_stripped"], "Hello world")

    def test_other_users_private_page_is_403(self):
        page = _page(self.project, self.owner, access=1)

        self.assertEqual(self.client_member.get(self.page_url(page)).status_code, 403)

    def test_owner_reads_own_private_page(self):
        page = _page(self.project, self.owner, access=1)

        self.assertEqual(self.client_owner.get(self.page_url(page)).status_code, 200)

    def test_page_of_another_project_is_404_under_this_project(self):
        other = _project(self.ws)
        _project_member(other, self.owner, ROLE_MEMBER)
        _project_member(other, self.member, ROLE_MEMBER)
        page = _page(other, self.owner)

        self.assertEqual(self.client_member.get(self.page_url(page)).status_code, 404)

    def test_unknown_page_is_404(self):
        class Ghost:
            id = uuid.uuid4()

        self.assertEqual(self.client_member.get(self.page_url(Ghost)).status_code, 404)


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------


class PatchKeepsBinaryHtmlConsistentTests(_Scenario):
    """THE test: html, plain text and the collaborative binary never disagree."""

    def test_html_patch_never_leaves_a_stale_binary_behind(self):
        page = _page(self.project, self.owner)
        self.assertEqual(bytes(_reload(page).description_binary), STALE_BINARY)

        with patch(TRANSACTION_TASK):
            response = self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        fresh = _reload(page)
        self.assertEqual(fresh.description_html, NEW_HTML)
        # The binary encoded the OLD table. Left in place, the live server would
        # load it on the next open and overwrite the new html on its next store.
        # It must be cleared so live regenerates it from description_html.
        self.assertIsNone(fresh.description_binary)
        # Same for the json derived from the old html.
        self.assertEqual(fresh.description_json, {})
        self.assertEqual(fresh.description_stripped, "ItemStatusSplashdone")

    def test_name_only_patch_also_invalidates_the_binary(self):
        # The Yjs binary carries the page title in its own `title` fragment; a
        # stale one would revert the rename through the live title-sync.
        page = _page(self.project, self.owner, name="Old name")

        with patch(TRANSACTION_TASK) as transaction_task:
            response = self.client_member.patch(self.page_url(page), {"name": "New name"}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        fresh = _reload(page)
        self.assertEqual(fresh.name, "New name")
        self.assertIsNone(fresh.description_binary)
        self.assertEqual(fresh.description_html, OLD_HTML)
        transaction_task.delay.assert_not_called()  # content did not change

    def test_embedding_is_requeued_with_the_new_text(self):
        page = _page(self.project, self.owner)
        self.mock_embed_entity.reset_mock()

        with patch(TRANSACTION_TASK):
            self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        texts = [call.kwargs["kwargs"]["text"] for call in self.mock_embed_entity.call_args_list]
        self.assertEqual(texts, ["ItemStatusSplashdone"])

    def test_response_reports_the_binary_was_cleared(self):
        page = _page(self.project, self.owner)

        with patch(TRANSACTION_TASK):
            body = self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json").json()

        self.assertTrue(body["changed"])
        self.assertTrue(body["description_binary_cleared"])
        self.assertEqual(body["description_html"], NEW_HTML)


class PatchBehaviourTests(_Scenario):
    def test_patch_records_page_log_task_and_a_restorable_version(self):
        from plane.db.models import PageVersion

        page = _page(self.project, self.owner)

        with patch(TRANSACTION_TASK) as transaction_task:
            self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        transaction_task.delay.assert_called_once_with(
            new_description_html=NEW_HTML, old_description_html=OLD_HTML, page_id=str(page.id)
        )
        version = PageVersion.objects.get(page=page)
        # The snapshot holds the OLD content, so the edit is undoable from the UI history.
        self.assertEqual(version.description_html, OLD_HTML)
        self.assertEqual(bytes(version.description_binary), STALE_BINARY)
        self.assertEqual(version.owned_by_id, self.member.id)

    def test_version_history_is_capped_at_twenty(self):
        from plane.db.models import PageVersion

        page = _page(self.project, self.owner)
        with patch(TRANSACTION_TASK):
            for index in range(23):
                html = f"<p>revision {index}</p>"
                self.client_member.patch(self.page_url(page), {"description_html": html}, format="json")

        self.assertEqual(PageVersion.objects.filter(page=page).count(), 20)

    def test_noop_patch_changes_nothing(self):
        from plane.db.models import PageVersion

        page = _page(self.project, self.owner)

        with patch(TRANSACTION_TASK) as transaction_task:
            body = self.client_member.patch(self.page_url(page), {"description_html": OLD_HTML}, format="json").json()

        self.assertFalse(body["changed"])
        self.assertEqual(bytes(_reload(page).description_binary), STALE_BINARY)
        self.assertEqual(PageVersion.objects.filter(page=page).count(), 0)
        transaction_task.delay.assert_not_called()

    def test_patch_preserves_created_by_and_stamps_updated_by(self):
        page = _page(self.project, self.owner)
        from plane.db.models import Page

        Page.objects.filter(pk=page.pk).update(created_by=self.owner)

        with patch(TRANSACTION_TASK):
            self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        fresh = _reload(page)
        self.assertEqual(fresh.created_by_id, self.owner.id)
        self.assertEqual(fresh.updated_by_id, self.member.id)
        self.assertEqual(fresh.owned_by_id, self.owner.id)

    def test_html_is_sanitized_before_it_is_stored(self):
        page = _page(self.project, self.owner)

        with patch(TRANSACTION_TASK):
            self.client_member.patch(
                self.page_url(page), {"description_html": "<p>ok</p><script>alert(1)</script>"}, format="json"
            )

        stored = _reload(page).description_html
        self.assertIn("ok", stored)
        self.assertNotIn("<script", stored)


class PatchRefusalTests(_Scenario):
    def _assert_untouched(self, page):
        fresh = _reload(page)
        self.assertEqual(fresh.description_html, OLD_HTML)
        self.assertEqual(bytes(fresh.description_binary), STALE_BINARY)

    def test_locked_page_is_refused_423(self):
        page = _page(self.project, self.owner, is_locked=True)

        with patch(TRANSACTION_TASK):
            response = self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["error_message"], "PAGE_LOCKED")
        self._assert_untouched(page)

    def test_archived_page_is_refused_409(self):
        page = _page(self.project, self.owner, archived_at=timezone.now().date())

        with patch(TRANSACTION_TASK):
            response = self.client_member.patch(self.page_url(page), {"name": "x"}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_message"], "PAGE_ARCHIVED")
        self._assert_untouched(page)

    def test_other_users_private_page_is_403_and_untouched(self):
        page = _page(self.project, self.owner, access=1)

        with patch(TRANSACTION_TASK):
            response = self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        self.assertEqual(response.status_code, 403)
        self._assert_untouched(page)

    def test_guest_cannot_patch_a_page_they_do_not_own(self):
        # Mirrors ProjectPagePermission: the owner of a page may always edit it,
        # a guest may not edit anyone else's.
        guest = _user()
        _workspace_member(self.ws, guest, ROLE_GUEST)
        _project_member(self.project, guest, ROLE_GUEST)
        page = _page(self.project, self.owner)

        with patch(TRANSACTION_TASK):
            response = _client(guest).patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        self.assertEqual(response.status_code, 403)
        self._assert_untouched(page)

    def test_page_of_another_project_is_404_and_untouched(self):
        other = _project(self.ws)
        _project_member(other, self.owner, ROLE_MEMBER)
        _project_member(other, self.member, ROLE_MEMBER)
        page = _page(other, self.owner)

        with patch(TRANSACTION_TASK):
            response = self.client_member.patch(self.page_url(page), {"description_html": NEW_HTML}, format="json")

        self.assertEqual(response.status_code, 404)
        self._assert_untouched(page)

    def test_bad_bodies_are_400_never_a_silent_noop(self):
        page = _page(self.project, self.owner)
        for body in (
            {},
            {"access": 1},  # silently dropped fields are the bug class this API refuses
            {"name": "ok", "is_locked": True},
            {"name": 5},
            {"description_html": ""},
            {"description_html": "   "},
            {"description_html": ["<p>x</p>"]},
        ):
            with patch(TRANSACTION_TASK):
                response = self.client_member.patch(self.page_url(page), body, format="json")
            self.assertEqual(response.status_code, 400, f"{body!r} -> {response.status_code}")
        self._assert_untouched(page)

    def test_non_object_body_is_400(self):
        page = _page(self.project, self.owner)

        response = self.client_member.patch(self.page_url(page), ["<p>x</p>"], format="json")

        self.assertEqual(response.status_code, 400)

    def test_unauthenticated_is_401(self):
        page = _page(self.project, self.owner)

        response = APIClient().patch(self.page_url(page), {"name": "x"}, format="json")

        self.assertEqual(response.status_code, 401)
