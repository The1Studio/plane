# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# DB integration tests (real Postgres) for project visibility. Mirrors the
# workload test style (TransactionTestCase + explicit ORM rows, no mocking the
# unit under test).

import uuid

from django.http import Http404
from django.test import TransactionTestCase

from plane.project_ext.service import (
    DEFAULT_PROJECT_MEMBER_ROLE,
    NETWORK_PUBLIC,
    NETWORK_SECRET,
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_MEMBER,
    add_project_members_bulk,
    list_all_projects,
    parse_network,
    parse_role,
    resolve_project_or_404,
    resolve_projects_or_404,
    resolve_target_user,
    resolve_workspace_or_404,
    set_visibility,
    set_visibility_bulk,
)


def _user():
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"user_{uid}", email=f"u-{uid}@test.invalid", password="x")


def _ws(slug=None):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=_user())


def _project(ws, network=NETWORK_PUBLIC):
    from plane.db.models import Project

    return Project.objects.create(
        workspace=ws,
        name=f"p-{uuid.uuid4().hex[:6]}",
        identifier=uuid.uuid4().hex[:5].upper(),
        network=network,
    )


def _workspace_member(ws, user, role=ROLE_ADMIN, is_active=True):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(workspace=ws, member=user, role=role, is_active=is_active)


def _project_member(project, user, role=ROLE_MEMBER, is_active=True):
    from plane.db.models import ProjectMember

    member = ProjectMember.objects.create(project=project, member=user, role=role)
    if not is_active:
        member.is_active = False
        member.save(update_fields=["is_active"])
    return member


class ParseNetworkTests(TransactionTestCase):
    def test_accepts_valid_ints_and_labels(self):
        for raw, expected in [
            (0, NETWORK_SECRET),
            (2, NETWORK_PUBLIC),
            ("0", NETWORK_SECRET),
            ("2", NETWORK_PUBLIC),
            ("secret", NETWORK_SECRET),
            ("private", NETWORK_SECRET),
            ("PUBLIC", NETWORK_PUBLIC),
        ]:
            network, error = parse_network(raw)
            self.assertIsNone(error, f"{raw!r} should parse")
            self.assertEqual(network, expected)

    def test_rejects_invalid_values(self):
        # 1 is a plausible-looking but invalid choice; None/bool/garbage must not
        # silently fall through to a default — that silent drop is the core bug
        # this app exists to fix.
        for raw in [None, 1, 3, -1, True, False, "", "yes", "kinda", {}, []]:
            network, error = parse_network(raw)
            self.assertIsNone(network, f"{raw!r} must not parse")
            self.assertTrue(error)


class SetVisibilityTests(TransactionTestCase):
    def test_flips_public_to_secret(self):
        ws = _ws()
        project = _project(ws, network=NETWORK_PUBLIC)

        payload = set_visibility(project, NETWORK_SECRET)

        project.refresh_from_db()
        self.assertEqual(project.network, NETWORK_SECRET)
        self.assertEqual(payload["network"], NETWORK_SECRET)
        self.assertEqual(payload["visibility"], "secret")

    def test_is_idempotent(self):
        ws = _ws()
        project = _project(ws, network=NETWORK_SECRET)

        set_visibility(project, NETWORK_SECRET)
        project.refresh_from_db()

        self.assertEqual(project.network, NETWORK_SECRET)

    def test_resolve_rejects_cross_workspace_project(self):
        owned = _project(_ws())
        other_slug = _ws().slug

        with self.assertRaises(Http404):
            resolve_project_or_404(other_slug, owned.id)


class SetVisibilityBulkTests(TransactionTestCase):
    def test_updates_every_listed_project(self):
        ws = _ws()
        projects = [_project(ws, network=NETWORK_PUBLIC) for _ in range(3)]

        payload, error = set_visibility_bulk(ws.slug, [str(p.id) for p in projects], NETWORK_SECRET)

        self.assertIsNone(error)
        self.assertEqual(payload["updated"], 3)
        for project in projects:
            project.refresh_from_db()
            self.assertEqual(project.network, NETWORK_SECRET)

    def test_counts_already_correct_projects_as_unchanged(self):
        ws = _ws()
        already = _project(ws, network=NETWORK_SECRET)
        todo = _project(ws, network=NETWORK_PUBLIC)

        payload, error = set_visibility_bulk(ws.slug, [str(already.id), str(todo.id)], NETWORK_SECRET)

        self.assertIsNone(error)
        self.assertEqual(payload["requested"], 2)
        self.assertEqual(payload["updated"], 1)
        self.assertEqual(payload["unchanged"], 1)

    def test_unknown_id_fails_whole_call_without_partial_update(self):
        ws = _ws()
        project = _project(ws, network=NETWORK_PUBLIC)
        stranger = _project(_ws(), network=NETWORK_PUBLIC)

        payload, error = set_visibility_bulk(ws.slug, [str(project.id), str(stranger.id)], NETWORK_SECRET)

        self.assertIsNone(payload)
        self.assertIn(str(stranger.id), error)
        project.refresh_from_db()
        self.assertEqual(project.network, NETWORK_PUBLIC, "no partial update on a failed bulk call")

    def test_rejects_empty_list(self):
        payload, error = set_visibility_bulk(_ws().slug, [], NETWORK_SECRET)

        self.assertIsNone(payload)
        self.assertTrue(error)


class ResolveWorkspaceOr404Tests(TransactionTestCase):
    def test_returns_workspace_for_known_slug(self):
        ws = _ws()

        self.assertEqual(resolve_workspace_or_404(ws.slug).id, ws.id)

    def test_raises_404_for_unknown_slug(self):
        with self.assertRaises(Http404):
            resolve_workspace_or_404(f"no-such-ws-{uuid.uuid4().hex[:8]}")


class ParseRoleTests(TransactionTestCase):
    def test_accepts_valid_ints_and_labels(self):
        for raw, expected in [
            (20, ROLE_ADMIN),
            (15, ROLE_MEMBER),
            (5, ROLE_GUEST),
            ("20", ROLE_ADMIN),
            ("admin", ROLE_ADMIN),
            ("Member", ROLE_MEMBER),
            ("GUEST", ROLE_GUEST),
        ]:
            role, error = parse_role(raw)
            self.assertIsNone(error, f"{raw!r} should parse")
            self.assertEqual(role, expected)

    def test_defaults_to_member_when_absent(self):
        role, error = parse_role(None)

        self.assertIsNone(error)
        self.assertEqual(role, DEFAULT_PROJECT_MEMBER_ROLE)
        self.assertEqual(role, ROLE_MEMBER)

    def test_rejects_invalid_values(self):
        for raw in [1, 3, -1, True, False, "", "owner", "kinda", {}, []]:
            role, error = parse_role(raw)
            self.assertIsNone(role, f"{raw!r} must not parse")
            self.assertTrue(error)


class ResolveTargetUserTests(TransactionTestCase):
    def test_resolves_by_user_id(self):
        user = _user()

        resolved, error = resolve_target_user(str(user.id), None)

        self.assertIsNone(error)
        self.assertEqual(resolved.id, user.id)

    def test_resolves_by_email_case_insensitive(self):
        user = _user()

        resolved, error = resolve_target_user(None, user.email.upper())

        self.assertIsNone(error)
        self.assertEqual(resolved.id, user.id)

    def test_requires_user_id_or_email(self):
        resolved, error = resolve_target_user(None, None)

        self.assertIsNone(resolved)
        self.assertTrue(error)

    def test_rejects_malformed_user_id(self):
        resolved, error = resolve_target_user("not-a-uuid", None)

        self.assertIsNone(resolved)
        self.assertTrue(error)

    def test_errors_when_user_not_found(self):
        resolved, error = resolve_target_user(str(uuid.uuid4()), None)

        self.assertIsNone(resolved)
        self.assertTrue(error)

        resolved, error = resolve_target_user(None, "nobody@test.invalid")

        self.assertIsNone(resolved)
        self.assertTrue(error)


class ListAllProjectsTests(TransactionTestCase):
    """list_all_projects takes an already-resolved workspace, not a slug — the
    404-for-unknown-slug behavior lives in resolve_workspace_or_404 (tested in
    ResolveWorkspaceOr404Tests above) and is exercised end-to-end via
    ProjectAllListAPIEndpoint.initial()."""

    def test_lists_every_project_including_private_ones(self):
        ws = _ws()
        admin = _user()
        _workspace_member(ws, admin, role=ROLE_ADMIN)
        public = _project(ws, network=NETWORK_PUBLIC)
        private = _project(ws, network=NETWORK_SECRET)

        payload = list_all_projects(ws, admin.id)

        self.assertEqual(payload["workspace_slug"], ws.slug)
        self.assertEqual(payload["count"], 2)
        ids = {row["id"] for row in payload["results"]}
        self.assertEqual(ids, {str(public.id), str(private.id)})

    def test_is_member_reflects_active_project_membership(self):
        ws = _ws()
        admin = _user()
        _workspace_member(ws, admin, role=ROLE_ADMIN)
        joined = _project(ws, network=NETWORK_SECRET)
        not_joined = _project(ws, network=NETWORK_SECRET)
        _project_member(joined, admin, role=ROLE_ADMIN)

        payload = list_all_projects(ws, admin.id)

        by_id = {row["id"]: row for row in payload["results"]}
        self.assertTrue(by_id[str(joined.id)]["is_member"])
        self.assertFalse(by_id[str(not_joined.id)]["is_member"])

    def test_cross_workspace_isolation(self):
        ws = _ws()
        admin = _user()
        _workspace_member(ws, admin, role=ROLE_ADMIN)
        _project(ws, network=NETWORK_SECRET)

        other_ws = _ws()
        stranger_project = _project(other_ws, network=NETWORK_PUBLIC)

        payload = list_all_projects(ws, admin.id)

        ids = {row["id"] for row in payload["results"]}
        self.assertNotIn(str(stranger_project.id), ids)


class ResolveProjectsOr404Tests(TransactionTestCase):
    def test_returns_every_project_when_all_owned(self):
        ws = _ws()
        projects = [_project(ws) for _ in range(3)]

        resolved = resolve_projects_or_404(ws.slug, [str(p.id) for p in projects])

        self.assertEqual({p.id for p in resolved}, {p.id for p in projects})

    def test_raises_404_when_any_id_is_unowned(self):
        ws = _ws()
        owned = _project(ws)
        stranger = _project(_ws())

        with self.assertRaises(Http404):
            resolve_projects_or_404(ws.slug, [str(owned.id), str(stranger.id)])


class AddProjectMembersBulkTests(TransactionTestCase):
    def test_creates_project_member_row_for_every_project(self):
        from plane.db.models import ProjectMember, ProjectUserProperty

        ws = _ws()
        projects = [_project(ws) for _ in range(2)]
        user = _user()
        _workspace_member(ws, user, role=ROLE_MEMBER)

        payload, error = add_project_members_bulk(ws.slug, [str(p.id) for p in projects], user, ROLE_MEMBER)

        self.assertIsNone(error)
        self.assertEqual(payload["user_id"], str(user.id))
        self.assertEqual(payload["email"], user.email)
        self.assertEqual(payload["role"], ROLE_MEMBER)
        self.assertEqual({r["project_id"] for r in payload["results"]}, {str(p.id) for p in projects})
        self.assertTrue(all(r["created"] for r in payload["results"]))
        for project in projects:
            self.assertTrue(ProjectMember.objects.filter(project=project, member=user, is_active=True).exists())
            # ProjectMember.save() must have created the matching sort-order
            # row — the same side effect core's bulk-add endpoint reproduces
            # by hand.
            self.assertTrue(ProjectUserProperty.objects.filter(project=project, user=user).exists())

    def test_reactivates_existing_inactive_member(self):
        from plane.db.models import ProjectMember

        ws = _ws()
        project = _project(ws)
        user = _user()
        _workspace_member(ws, user, role=ROLE_MEMBER)
        _project_member(project, user, role=ROLE_GUEST, is_active=False)

        payload, error = add_project_members_bulk(ws.slug, [str(project.id)], user, ROLE_ADMIN)

        self.assertIsNone(error)
        self.assertEqual(payload["results"], [{"project_id": str(project.id), "created": False}])
        member = ProjectMember.objects.get(project=project, member=user)
        self.assertTrue(member.is_active)
        self.assertEqual(member.role, ROLE_ADMIN)

    def test_idempotent_readd_returns_created_false(self):
        ws = _ws()
        project = _project(ws)
        user = _user()
        _workspace_member(ws, user, role=ROLE_MEMBER)

        first, error = add_project_members_bulk(ws.slug, [str(project.id)], user, ROLE_MEMBER)
        self.assertIsNone(error)
        self.assertTrue(first["results"][0]["created"])

        second, error = add_project_members_bulk(ws.slug, [str(project.id)], user, ROLE_MEMBER)
        self.assertIsNone(error)
        self.assertFalse(second["results"][0]["created"])

    def test_rejects_user_not_in_workspace(self):
        from plane.db.models import ProjectMember

        ws = _ws()
        project = _project(ws)
        user = _user()  # never added to ws via WorkspaceMember

        payload, error = add_project_members_bulk(ws.slug, [str(project.id)], user, ROLE_MEMBER)

        self.assertIsNone(payload)
        self.assertTrue(error)
        self.assertFalse(ProjectMember.objects.filter(project=project, member=user).exists())

    def test_unowned_project_id_fails_whole_call_without_partial_apply(self):
        from plane.db.models import ProjectMember

        ws = _ws()
        owned = _project(ws)
        stranger_project = _project(_ws())
        user = _user()
        _workspace_member(ws, user, role=ROLE_MEMBER)

        with self.assertRaises(Http404):
            add_project_members_bulk(ws.slug, [str(owned.id), str(stranger_project.id)], user, ROLE_MEMBER)

        # no partial update on a failed bulk call
        self.assertFalse(ProjectMember.objects.filter(project=owned, member=user).exists())

    def test_rejects_empty_project_ids(self):
        payload, error = add_project_members_bulk(_ws().slug, [], _user(), ROLE_MEMBER)

        self.assertIsNone(payload)
        self.assertTrue(error)
