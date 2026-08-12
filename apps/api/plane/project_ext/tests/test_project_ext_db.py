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
    NETWORK_PUBLIC,
    NETWORK_SECRET,
    parse_network,
    resolve_project_or_404,
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
