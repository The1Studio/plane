# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Contract tests for GET /api/v1/users/me/workspaces/.

This endpoint exists so an API-key client can discover the workspace slug that
every other v1 route requires as a path segment. Before it, that value could be
neither listed nor probed -- an unknown slug and a real workspace the caller
cannot access both answer 403 with identical bodies (issue #29).

The membership filter is the load-bearing part, so it is pinned from both
sides: a workspace the caller belongs to must appear, and one they do not (or
no longer) belong to must not. Leaking a slug here would be worse than the gap
it closes.
"""

import pytest
from rest_framework import status

from plane.db.models import Workspace, WorkspaceMember


@pytest.mark.contract
class TestUserWorkspacesContract:
    """Test workspace discovery against a live endpoint."""

    URL = "/api/v1/users/me/workspaces/"

    @pytest.mark.django_db
    def test_requires_authentication(self, api_client):
        response = api_client.get(self.URL)

        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    @pytest.mark.django_db
    def test_api_key_can_list_its_own_workspaces(self, api_key_client, workspace):
        response = api_key_client.get(self.URL)

        assert response.status_code == status.HTTP_200_OK
        slugs = [w["slug"] for w in response.json()]
        assert workspace.slug in slugs

    @pytest.mark.django_db
    def test_returns_the_fields_a_client_needs_to_bootstrap(
        self, api_key_client, workspace
    ):
        response = api_key_client.get(self.URL)

        entry = next(w for w in response.json() if w["slug"] == workspace.slug)
        # `slug` is the whole point -- it is the path segment every other v1
        # route takes. name/id come along for display and joins.
        assert set(entry.keys()) == {"name", "slug", "id"}
        assert entry["name"] == workspace.name

    @pytest.mark.django_db
    def test_empty_list_when_the_user_belongs_to_nothing(self, api_key_client):
        response = api_key_client.get(self.URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.django_db
    def test_does_not_leak_a_workspace_the_caller_is_not_a_member_of(
        self, api_key_client, create_user, workspace
    ):
        # A second workspace owned by nobody the caller is a member of. If the
        # membership filter were dropped, this slug would be handed to a client
        # that cannot use it -- the endpoint would become a workspace-slug
        # oracle for the whole instance.
        Workspace.objects.create(
            name="Someone Else's Workspace",
            owner=create_user,
            slug="not-my-workspace",
        )

        response = api_key_client.get(self.URL)

        slugs = [w["slug"] for w in response.json()]
        assert "not-my-workspace" not in slugs
        assert workspace.slug in slugs

    @pytest.mark.django_db
    def test_deactivated_membership_is_excluded(self, api_key_client, workspace):
        # A revoked membership must not resurface the slug: every subsequent
        # call with it would 403, so returning it is actively misleading.
        WorkspaceMember.objects.filter(workspace=workspace).update(is_active=False)

        response = api_key_client.get(self.URL)

        assert response.status_code == status.HTTP_200_OK
        assert workspace.slug not in [w["slug"] for w in response.json()]
