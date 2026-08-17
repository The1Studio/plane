# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# DB integration tests (real Postgres) for workspace discovery. Mirrors the
# project_ext / workload test style (TransactionTestCase + explicit ORM rows,
# no mocking the unit under test).
#
# The membership filter is the load-bearing part and is pinned from BOTH sides.
# Dropping it would turn this endpoint into a workspace-slug oracle for the
# whole instance — which is strictly worse than the discovery gap it closes, so
# the negative cases matter more than the positive one.

import uuid

from django.test import TransactionTestCase

ROLE_ADMIN = 20


def _user():
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"user_{uid}", email=f"u-{uid}@test.invalid", password="x")


def _ws(slug=None, owner=None):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner or _user())


def _workspace_member(ws, user, role=ROLE_ADMIN, is_active=True):
    from plane.db.models import WorkspaceMember

    return WorkspaceMember.objects.create(workspace=ws, member=user, role=role, is_active=is_active)


def _discoverable(user):
    """The queryset the endpoint serves, exercised directly against the DB."""
    from plane.db.models import Workspace

    return list(
        Workspace.objects.filter(
            workspace_member__member=user,
            workspace_member__is_active=True,
        )
        .distinct()
        .order_by("name")
        .values_list("slug", flat=True)
    )


class UserWorkspaceDiscoveryTests(TransactionTestCase):
    def test_lists_a_workspace_the_user_belongs_to(self):
        user = _user()
        ws = _ws()
        _workspace_member(ws, user)

        self.assertIn(ws.slug, _discoverable(user))

    def test_empty_when_the_user_belongs_to_nothing(self):
        user = _user()
        _ws()  # exists, but the user is not a member

        self.assertEqual(_discoverable(user), [])

    def test_does_not_leak_a_workspace_the_user_is_not_a_member_of(self):
        user = _user()
        mine = _ws()
        _workspace_member(mine, user)
        theirs = _ws()  # someone else's

        slugs = _discoverable(user)
        self.assertIn(mine.slug, slugs)
        self.assertNotIn(theirs.slug, slugs)

    def test_deactivated_membership_is_excluded(self):
        # A revoked membership must not resurface the slug: every subsequent
        # call with it would 403, so returning it is actively misleading.
        user = _user()
        ws = _ws()
        _workspace_member(ws, user, is_active=False)

        self.assertNotIn(ws.slug, _discoverable(user))

    def test_multiple_memberships_are_deduplicated_and_ordered(self):
        user = _user()
        b = _ws(slug="zzz-workspace")
        a = _ws(slug="aaa-workspace")
        _workspace_member(a, user)
        _workspace_member(b, user)

        slugs = _discoverable(user)
        self.assertEqual(slugs, sorted(slugs))
        self.assertEqual(len(slugs), len(set(slugs)))


class UserWorkspaceRouteTests(TransactionTestCase):
    def test_route_is_registered_and_does_not_shadow_core_users_me(self):
        # This app's urls are included BEFORE plane.api.urls, so a bare
        # `users/me/` here would silently shadow core's endpoint. Assert both
        # resolve to their intended views.
        from django.urls import resolve

        from plane.api.views import UserEndpoint
        from plane.workspace_ext.api_views import UserWorkspacesAPIEndpoint

        discovery = resolve("/api/v1/users/me/workspaces/")
        core = resolve("/api/v1/users/me/")

        self.assertIs(discovery.func.view_class, UserWorkspacesAPIEndpoint)
        self.assertIs(core.func.view_class, UserEndpoint)
