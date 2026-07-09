# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P0 — webhook ingest spine tests: HMAC verify-before-parse, constant-time
# compare, redelivery idempotency, fast-ack + Celery enqueue, and the
# installation bootstrap -> RepoProjectMap auto-seed pipeline.
#
# Mirrors the ai_ext/workload test style: TransactionTestCase (on_commit
# callbacks only fire on a real commit — a plain TestCase would roll back
# and silently skip the enqueue), explicit ORM rows, real Postgres, no
# mocking of the unit under test (only `route_event.apply_async` + spies).
#
# All payloads are mocked fixture JSON under tests/fixtures/ — no real
# GitHub credentials anywhere in this file.

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
from unittest import mock

from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client, TransactionTestCase

WEBHOOK_URL = "/api/github/webhook/"
WEBHOOK_SECRET = "test-github-webhook-secret"

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture / signing helpers
# ---------------------------------------------------------------------------

def _load_fixture(name):
    with open(_FIXTURES_DIR / name) as f:
        return json.load(f)


def _raw_body(payload):
    """Byte-for-byte match of what django.test.Client.post(..., data=payload,
    content_type="application/json") sends on the wire (Client._encode_json
    does json.dumps(data, cls=DjangoJSONEncoder))."""
    return json.dumps(payload, cls=DjangoJSONEncoder).encode("utf-8")


def _sign(secret, raw_body):
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def _post_webhook(client, payload, event_type, delivery_id=None, secret=WEBHOOK_SECRET, sign=True):
    delivery_id = delivery_id or str(uuid.uuid4())
    extra = {
        "content_type": "application/json",
        "HTTP_X_GITHUB_EVENT": event_type,
        "HTTP_X_GITHUB_DELIVERY": delivery_id,
    }
    if sign:
        raw_body = _raw_body(payload)
        extra["HTTP_X_HUB_SIGNATURE_256"] = _sign(secret, raw_body)
    response = client.post(WEBHOOK_URL, data=payload, **extra)
    return response, delivery_id


# ---------------------------------------------------------------------------
# ORM helpers (mirror workload/ai_ext test style)
# ---------------------------------------------------------------------------

def _user(email=None, is_bot=False):
    from plane.db.models import User

    uid = uuid.uuid4().hex[:8]
    email = email or f"u-{uid}@test.invalid"
    return User.objects.create_user(username=f"user_{uid}", email=email, password="x", is_bot=is_bot)


def _workspace(slug=None, owner=None):
    from plane.db.models import Workspace

    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    owner = owner or _user()
    return Workspace.objects.create(name=slug, slug=slug, logo="", owner=owner)


def _project(ws, name, identifier):
    from plane.db.models import Project

    return Project.objects.create(workspace=ws, name=name, identifier=identifier)


def _bind_github_workspace(ws):
    """Create the WorkspaceIntegration row that services/installation.py
    resolves a workspace through (the out-of-band admin bootstrap step —
    see models.py GithubInstallation docstring)."""
    from plane.db.models import APIToken, Integration, WorkspaceIntegration

    bot_user = _user(is_bot=True)
    integration, _ = Integration.objects.get_or_create(
        provider="github", defaults={"title": "GitHub", "network": 1}
    )
    api_token = APIToken.objects.create(user=bot_user, workspace=ws, is_service=True)
    return WorkspaceIntegration.objects.create(
        workspace=ws, actor=bot_user, integration=integration, api_token=api_token
    )


class GithubWebhookTests(TransactionTestCase):
    def setUp(self):
        self.client = Client()
        # Provide the webhook secret the view resolves via os.environ
        # (GITHUB_WEBHOOK_SECRET → Integration.webhook_secret fallback). Without
        # it, verify_signature fails closed and every signed request 401s.
        env = mock.patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET})
        env.start()
        self.addCleanup(env.stop)

    # -- Valid signature -------------------------------------------------

    @mock.patch("plane.github_ext.bgtasks.dispatch.route_event.apply_async")
    def test_valid_signature_returns_202_and_enqueues_dispatch(self, mock_apply_async):
        from plane.github_ext.models import WebhookDelivery

        payload = _load_fixture("push_event.json")
        response, delivery_id = _post_webhook(self.client, payload, "push")

        self.assertEqual(response.status_code, 202)

        delivery = WebhookDelivery.objects.get(delivery_id=delivery_id)
        self.assertEqual(delivery.event_type, "push")

        mock_apply_async.assert_called_once_with(
            args=[delivery.id], kwargs={"payload": payload}
        )

    # -- Bad signature -----------------------------------------------------

    @mock.patch("plane.github_ext.bgtasks.dispatch.route_event.apply_async")
    def test_bad_signature_returns_401_and_no_work_done(self, mock_apply_async):
        # Behavioral proof of verify-before-parse: a bad signature is rejected
        # before the view parses JSON, creates a WebhookDelivery, or enqueues
        # dispatch. (Spying on json.loads is unreliable — `json` is a shared
        # module and Django staticfiles calls json.loads during the request.)
        from plane.github_ext.models import WebhookDelivery

        payload = _load_fixture("push_event.json")
        response, delivery_id = _post_webhook(
            self.client, payload, "push", secret="wrong-secret-entirely"
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(
            WebhookDelivery.objects.filter(delivery_id=delivery_id).exists()
        )
        mock_apply_async.assert_not_called()

    # -- Missing signature header -------------------------------------------

    def test_missing_signature_header_returns_401(self):
        payload = _load_fixture("push_event.json")

        response, _ = _post_webhook(self.client, payload, "push", sign=False)

        self.assertEqual(response.status_code, 401)

    # -- Redelivery idempotency ---------------------------------------------

    @mock.patch("plane.github_ext.bgtasks.dispatch.route_event.apply_async")
    def test_duplicate_delivery_returns_200_no_second_enqueue(self, mock_apply_async):
        payload = _load_fixture("push_event.json")
        delivery_id = str(uuid.uuid4())

        first, _ = _post_webhook(self.client, payload, "push", delivery_id=delivery_id)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(mock_apply_async.call_count, 1)

        second, _ = _post_webhook(self.client, payload, "push", delivery_id=delivery_id)
        self.assertEqual(second.status_code, 200)
        # No second enqueue on redelivery.
        self.assertEqual(mock_apply_async.call_count, 1)

    # -- Constant-time compare ------------------------------------------------

    def test_signature_compare_uses_hmac_compare_digest(self):
        # Unit-test verify_signature() directly (no HTTP request) so nothing
        # else in the stack touches the shared hmac module — proving the
        # constant-time primitive is used, with no staticfiles-manifest noise.
        from plane.github_ext.webhook import verify as verify_mod

        raw = b'{"zen": "constant-time"}'
        sig = _sign(WEBHOOK_SECRET, raw)

        with mock.patch.object(
            verify_mod.hmac, "compare_digest", side_effect=hmac.compare_digest
        ) as mock_compare:
            ok = verify_mod.verify_signature(WEBHOOK_SECRET, raw, sig)

        self.assertTrue(ok)
        mock_compare.assert_called_once_with(sig, sig)

    # -- Installation bootstrap + RepoProjectMap auto-seed -------------------

    @mock.patch("plane.github_ext.bgtasks.dispatch.route_event.apply_async")
    def test_installation_event_upserts_installation_and_seeds_repo_map(self, _mock_apply_async):
        from plane.github_ext.bgtasks.dispatch import route_event
        from plane.github_ext.models import GithubInstallation, RepoProjectMap, WebhookDelivery

        ws = _workspace()
        _bind_github_workspace(ws)
        matched_project = _project(ws, name="plane-core", identifier="PLANE")

        payload = _load_fixture("installation_created.json")
        response, delivery_id = _post_webhook(self.client, payload, "installation")
        self.assertEqual(response.status_code, 202)

        delivery = WebhookDelivery.objects.get(delivery_id=delivery_id)

        # Simulate the Celery worker picking up the (mocked) enqueue.
        route_event(delivery.id, payload=payload)

        installation = GithubInstallation.objects.get(installation_id="987654")
        self.assertEqual(installation.account_login, "the1studio")
        self.assertEqual(installation.workspace_id, ws.id)

        matched_map = RepoProjectMap.objects.get(
            installation=installation, repo_full_name="the1studio/plane-core"
        )
        self.assertEqual(matched_map.project_id, matched_project.id)

        unmatched_map = RepoProjectMap.objects.get(
            installation=installation, repo_full_name="the1studio/unmatched-repo"
        )
        self.assertIsNone(unmatched_map.project_id)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "processed")
