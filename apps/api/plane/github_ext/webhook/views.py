# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Inbound GitHub App webhook receiver (P0 — ingest spine).
#
# Order is LOAD-BEARING (see phase-P0.md risk table — HMAC-bypass is the
# top-scored risk):
#   (a) read request.body RAW           -> before anything else touches it
#   (b) resolve secret + verify_signature -> 401 on fail, BEFORE any parsing
#   (c) json.loads the body              -> only after (b) succeeds
#   (d) WebhookDelivery.get_or_create on X-GitHub-Delivery -> 200 no-op if
#       this delivery was already processed (redelivery)
#   (e) transaction.on_commit(...) enqueue route_event -> never enqueue
#       before the delivery row is durably committed
#   (f) 202 Accepted -> all real work happens in Celery, fast-ack avoids
#       GitHub's ~10s webhook timeout + retry storm
#
# Auth IS the HMAC signature: no session/API-token auth applies to this
# endpoint (AllowAny + no authentication_classes).

import json
import logging
import os

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView

from .verify import verify_signature

logger = logging.getLogger("plane.github_ext")

# Allowlisted headers persisted on WebhookDelivery for debugging. Never the
# full header set — Authorization / cookies / anything auth-bearing is
# deliberately excluded (models.py WebhookDelivery docstring).
_SAFE_HEADER_ALLOWLIST = (
    "X-GitHub-Event",
    "X-GitHub-Delivery",
    "X-Hub-Signature-256",
    "X-GitHub-Hook-Id",
    "X-GitHub-Hook-Installation-Target-Id",
    "X-GitHub-Hook-Installation-Target-Type",
    "Content-Type",
    "User-Agent",
)


def _safe_headers(request) -> dict:
    return {key: request.headers[key] for key in _SAFE_HEADER_ALLOWLIST if key in request.headers}


def _resolve_secret():
    """GITHUB_WEBHOOK_SECRET env var, falling back to the dormant
    Integration(provider="github").webhook_secret row. Never raises: an
    absent env var, absent Integration row, or DB error simply yields no
    secret, which fails signature verification closed (401)."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if secret:
        return secret

    try:
        from plane.db.models import Integration

        integration = Integration.objects.filter(provider="github").first()
    except Exception:  # pragma: no cover - defensive (DB unavailable, etc.)
        integration = None

    if integration and integration.webhook_secret:
        return integration.webhook_secret

    return None


class GithubWebhookView(BaseAPIView):
    """POST /api/github/webhook/ — receives GitHub App webhook deliveries."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        # (a) raw body bytes — read before anything else touches the stream.
        raw_body = request.body

        # (b) resolve secret + verify BEFORE any parsing.
        secret = _resolve_secret()
        signature_header = request.headers.get("X-Hub-Signature-256")
        if not verify_signature(secret, raw_body, signature_header):
            return Response({"error": "invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

        # (c) only now is it safe to parse JSON.
        try:
            payload = json.loads(raw_body)
        except (ValueError, TypeError):
            return Response({"error": "invalid JSON body"}, status=status.HTTP_400_BAD_REQUEST)

        event_type = request.headers.get("X-GitHub-Event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery")
        if not delivery_id:
            return Response(
                {"error": "missing X-GitHub-Delivery"}, status=status.HTTP_400_BAD_REQUEST
            )

        from plane.github_ext.models import WebhookDelivery

        delivery, created = WebhookDelivery.objects.get_or_create(
            delivery_id=delivery_id,
            defaults={
                "event_type": event_type,
                "headers": _safe_headers(request),
                "status": "received",
            },
        )

        if not created:
            # (d) redelivery — idempotent no-op, never re-enqueue.
            logger.debug("GithubWebhookView: duplicate delivery %s — no-op", delivery_id)
            return Response(status=status.HTTP_200_OK)

        # (e) fast-ack: enqueue AFTER the delivery row is durably committed.
        from plane.github_ext.bgtasks.dispatch import route_event

        transaction.on_commit(
            lambda: route_event.apply_async(args=[delivery.id], kwargs={"payload": payload})
        )

        # (f) 202 Accepted — heavy work happens in Celery, never inline here.
        return Response(status=status.HTTP_202_ACCEPTED)
