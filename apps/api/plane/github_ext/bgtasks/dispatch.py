# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P0 — fast-ack dispatch task. Enqueued via transaction.on_commit from
# webhook/views.py (mirrors ai_ext/signals.py:40-51). Runs on the default
# Celery queue (no CELERY_TASK_ROUTES entry needed for the P0 MVP — see
# plan §2 tp1).

import logging

from celery import shared_task

logger = logging.getLogger("plane.github_ext")

_INSTALLATION_EVENTS = ("installation", "installation_repositories")
# P1 — dev-workflow link parsing (branch/PR/commit -> WorkItemGithubLink).
_LINK_EVENTS = ("push", "pull_request")
# P0 ingests these but does no work yet — P2 (state transitions) and P3
# (comment sync) fill these handlers in.
_NOOP_EVENTS = ("issues", "issue_comment")


@shared_task(
    name="plane.github_ext.bgtasks.dispatch.route_event",
    bind=True,
    max_retries=2,
)
def route_event(self, delivery_id, payload=None):
    """Route a verified, deduplicated webhook delivery to its handler.

    `payload` is passed straight through from the webhook view (never
    persisted — WebhookDelivery only stores headers + status, never the
    body). Marks WebhookDelivery.status "processed" / "failed".
    """
    from plane.github_ext.models import WebhookDelivery

    try:
        delivery = WebhookDelivery.objects.get(id=delivery_id)
    except WebhookDelivery.DoesNotExist:
        logger.warning("route_event: unknown delivery id %s", delivery_id)
        return

    payload = payload or {}
    event_type = delivery.event_type

    try:
        if event_type in _INSTALLATION_EVENTS:
            from plane.github_ext.services.installation import handle_installation_event
            from plane.github_ext.services.repo_map import seed_repo_project_map

            installation = handle_installation_event(event_type, payload)
            if installation is not None:
                seed_repo_project_map(installation, event_type, payload)
        elif event_type in _LINK_EVENTS:
            from plane.github_ext.bgtasks.link_task import process_refs

            # Direct synchronous call, not `.apply_async()` — see
            # bgtasks/link_task.py module docstring for why (mirrors the
            # installation-handling pattern immediately above).
            process_refs(event_type, payload=payload)

            # P2 — pull_request lifecycle also drives state automation
            # (independent of the P1 link write above).
            if event_type == "pull_request":
                from plane.github_ext.bgtasks.transition_task import process_pr_transition

                process_pr_transition(payload=payload)
        elif event_type in _NOOP_EVENTS:
            logger.debug(
                "route_event: %s is a no-op in P0 (delivery=%s)", event_type, delivery_id
            )
        else:
            logger.debug(
                "route_event: unhandled event_type=%s (delivery=%s)", event_type, delivery_id
            )
    except Exception:
        delivery.status = "failed"
        delivery.save(update_fields=["status"])
        raise

    delivery.status = "processed"
    delivery.save(update_fields=["status"])
