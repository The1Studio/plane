# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P3 — AI digest background tasks (2-task Batch pattern).
# T1: submit_digest_batch — gather content, submit Anthropic Batch, store batch_id + receivers.
# T2: poll_digest_batches — beat poller (~10 min) retrieves ended batches, fans out Notifications.

import json
import logging
import uuid

from celery import shared_task
from django.utils import timezone

from plane.ai_ext.clients.anthropic_client import MODEL_SONNET, AnthropicClient, wrap_untrusted
from plane.ai_ext.gate import AiGateError, gate_or_raise

logger = logging.getLogger("plane.ai_ext")

_DIGEST_SYSTEM = (
    "You are a project assistant. Summarize the recent activity in this Plane project or cycle. "
    "Be concise (3-5 bullet points). Focus on completed work, blockers, and next priorities. "
    "Do not invent information not present in the data."
)

_MAX_CONTEXT_TOKENS = 100_000  # map-reduce fallback above this


# ------------------------------------------------------------------
# T1: submit digest batch
# ------------------------------------------------------------------


@shared_task(
    name="plane.ai_ext.bgtasks.digest_task.submit_digest_batch",
    bind=True,
    max_retries=0,
)
def submit_digest_batch(self, workspace_id: str, project_id: str | None = None, cycle_id: str | None = None):
    """Build and submit a Batch for digest generation.

    Persists AiBatchJob row with receivers_map so the poller can fan out.
    Re-checks enabled + ceiling at enqueue.
    """
    try:
        config = gate_or_raise(workspace_id)
    except AiGateError as exc:
        logger.info("submit_digest_batch: AI gate blocked — %s", exc.message)
        return

    from plane.db.models import Issue, ProjectMember, WorkspaceMember
    from plane.db.models import UserNotificationPreference
    from plane.ai_ext.models import AiBatchJob

    # ------------------------------------------------------------------
    # Gather content (issues/comments active in last 7 days).
    # ------------------------------------------------------------------
    entity_label = project_id or cycle_id or workspace_id
    qs = Issue.issue_objects.filter(workspace_id=workspace_id)
    if project_id:
        qs = qs.filter(project_id=project_id)
    if cycle_id:
        qs = qs.filter(issue_cycle__cycle_id=cycle_id)

    recent_issues = list(
        qs.filter(updated_at__gte=timezone.now() - timezone.timedelta(days=7))
        .values("name", "priority", "state__name", "updated_at")[:200]
    )

    if not recent_issues:
        logger.info("submit_digest_batch: no activity for %s — 0 tokens", entity_label)
        return

    context_text = "\n".join(
        f"- [{i['state__name']}] {i['name']} (priority={i['priority']})"
        for i in recent_issues
    )

    # Map-reduce fallback: if context is huge, summarize in chunks.
    approx_tokens = len(context_text) // 4
    if approx_tokens > _MAX_CONTEXT_TOKENS:
        context_text = _map_reduce_summarize(context_text, workspace_id, config)

    # ------------------------------------------------------------------
    # C3 FIX: Find opted-in receivers only.
    #
    # We filter to active workspace/project members whose
    # UserNotificationPreference.property_change is True (the closest existing
    # opt-in signal — no digest-specific field exists in the schema).  Members
    # with NO preference row are treated as opted-in (default True per Django
    # field default).  Members who have explicitly set property_change=False
    # are excluded as opted-out.
    #
    # C4 FIX: When project_id or cycle_id is set, restrict receivers to active
    # ProjectMember of that specific project (cycle-scoped digest → cycle's
    # project members only).  Workspace-level digests use all workspace members.
    # ------------------------------------------------------------------
    if project_id:
        # Project-scoped or cycle-scoped digest: receivers = active project members.
        scope_project_id = project_id
    elif cycle_id:
        # Derive project from the cycle.
        from plane.db.models import Cycle
        try:
            scope_project_id = str(
                Cycle.objects.filter(id=cycle_id).values_list("project_id", flat=True).get()
            )
        except Cycle.DoesNotExist:
            logger.warning("submit_digest_batch: cycle %s not found", cycle_id)
            return
    else:
        scope_project_id = None

    if scope_project_id:
        # C4: restrict receivers to active ProjectMember of the scoped project.
        candidate_ids = list(
            ProjectMember.objects.filter(
                workspace_id=workspace_id,
                project_id=scope_project_id,
                is_active=True,
            ).values_list("member_id", flat=True)
        )
    else:
        # Workspace-level digest: all active workspace members.
        candidate_ids = list(
            WorkspaceMember.objects.filter(workspace_id=workspace_id, is_active=True)
            .values_list("member_id", flat=True)
        )

    # C3: exclude explicit opt-outs (property_change=False for this workspace).
    opted_out_ids = set(
        UserNotificationPreference.objects.filter(
            workspace_id=workspace_id,
            user_id__in=candidate_ids,
            property_change=False,
        ).values_list("user_id", flat=True)
    )
    receiver_ids = [uid for uid in candidate_ids if uid not in opted_out_ids][:100]

    if not receiver_ids:
        logger.info("submit_digest_batch: no opted-in receivers for %s", entity_label)
        return

    # ------------------------------------------------------------------
    # Build one Batch request per receiver.
    # ------------------------------------------------------------------
    batch_requests = []
    receivers_map = {}
    for receiver_id in receiver_ids:
        custom_id = str(uuid.uuid4())
        receivers_map[custom_id] = {
            "receiver_id": str(receiver_id),
            "entity_type": "project" if project_id else ("cycle" if cycle_id else "workspace"),
            "entity_id": str(project_id or cycle_id or workspace_id),
        }
        batch_requests.append(
            {
                "custom_id": custom_id,
                "model": MODEL_SONNET,
                "max_tokens": 512,
                "system": _DIGEST_SYSTEM,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Summarize recent project activity for this user:\n"
                            + wrap_untrusted(context_text)
                        ),
                    }
                ],
            }
        )

    # H3 FIX: pre-reserve estimated cost before submitting the Batch so the
    # ceiling check is atomic (INCRBY-then-rollback pattern in CostTracker).
    # Estimate: Sonnet input+output tokens per receiver × token cost.
    # Rough: 512 output + ~len(context_text)//4 input tokens per receiver.
    # Sonnet price ≈ $3/M input + $15/M output (2025); use conservative estimate.
    _SONNET_INPUT_COST_PER_TOKEN = 3.0 / 1_000_000
    _SONNET_OUTPUT_COST_PER_TOKEN = 15.0 / 1_000_000
    input_tokens_each = len(context_text) // 4
    output_tokens_each = 512
    estimated_cost = len(batch_requests) * (
        input_tokens_each * _SONNET_INPUT_COST_PER_TOKEN
        + output_tokens_each * _SONNET_OUTPUT_COST_PER_TOKEN
    )
    from plane.ai_ext.cost_tracker import CostTracker, CostCeilingExceeded
    try:
        CostTracker(workspace_id).pre_reserve(estimated_cost, config.monthly_usd_ceiling)
    except CostCeilingExceeded as exc:
        logger.warning("submit_digest_batch: pre-reserve blocked — %s", exc)
        return

    client = AnthropicClient(workspace_id=workspace_id)
    try:
        batch_id = client.batch_submit(batch_requests)
    except Exception as exc:
        logger.exception("submit_digest_batch: Batch submit failed — %s", exc)
        return

    AiBatchJob.objects.create(
        workspace_id=workspace_id,
        batch_id=batch_id,
        job_type="digest",
        receivers_map=receivers_map,
        status="in_progress",
    )
    logger.info("submit_digest_batch: submitted batch %s (%d receivers)", batch_id, len(receiver_ids))


# ------------------------------------------------------------------
# T2: beat poller — retrieve ended batches and fan out
# ------------------------------------------------------------------


@shared_task(
    name="plane.ai_ext.bgtasks.digest_task.poll_digest_batches",
    bind=True,
    max_retries=0,
)
def poll_digest_batches(self):
    """Beat poller (run every ~10 min via PeriodicTask).

    Fetches all in-progress digest batches, checks Anthropic for status,
    and fans out Notification rows when a batch ends.
    """
    from plane.ai_ext.models import AiBatchJob

    pending = AiBatchJob.objects.filter(status="in_progress", job_type="digest")
    for job in pending:
        try:
            _process_batch_job(job)
        except Exception as exc:
            logger.exception("poll_digest_batches: error processing batch %s — %s", job.batch_id, exc)


def _process_batch_job(job):
    from plane.ai_ext.models import AiBatchJob
    from plane.db.models import Notification, User, Workspace, Project

    # Check gate for this workspace before fan-out.
    try:
        gate_or_raise(job.workspace_id)
    except AiGateError:
        # Workspace was disabled; mark canceled and skip.
        AiBatchJob.objects.filter(pk=job.pk).update(status="canceled")
        return

    client = AnthropicClient(workspace_id=str(job.workspace_id))
    batch_status = client.batch_poll(job.batch_id)

    if batch_status.processing_status not in ("ended",):
        # Still in progress or canceled — check expiry.
        if batch_status.processing_status in ("expired", "canceled"):
            AiBatchJob.objects.filter(pk=job.pk).update(
                status=batch_status.processing_status,
                ended_at=timezone.now(),
            )
        return

    # Batch ended — collect results.
    results_by_custom_id = {}
    for result in client.batch_results(job.batch_id):
        if result.result.type == "succeeded":
            text = ""
            for block in result.result.message.content:
                if block.type == "text":
                    text = block.text
                    break
            results_by_custom_id[result.custom_id] = text

    # Fan out one Notification per receiver.
    workspace = Workspace.objects.get(pk=job.workspace_id)
    notifications = []
    for custom_id, mapping in job.receivers_map.items():
        text = results_by_custom_id.get(custom_id, "")
        if not text:
            continue
        receiver_id = mapping["receiver_id"]
        notifications.append(
            Notification(
                workspace=workspace,
                project=None,
                entity_identifier=None,
                entity_name=mapping["entity_type"],
                title="AI project digest",
                message={"text": text},
                message_html=f"<p>{text}</p>",
                message_stripped=text,
                sender="AI Digest",
                triggered_by=None,
                receiver_id=receiver_id,
                data={"batch_id": job.batch_id, "entity_id": mapping["entity_id"]},
            )
        )

    if notifications:
        Notification.objects.bulk_create(notifications, batch_size=100, ignore_conflicts=True)
        logger.info(
            "poll_digest_batches: fanned out %d notifications for batch %s",
            len(notifications),
            job.batch_id,
        )

    AiBatchJob.objects.filter(pk=job.pk).update(
        status="ended",
        ended_at=timezone.now(),
    )


def _map_reduce_summarize(full_text: str, workspace_id: str, config) -> str:
    """Summarize long context via map-reduce (chunked Haiku calls)."""
    from plane.ai_ext.clients.anthropic_client import MODEL_HAIKU

    client = AnthropicClient(workspace_id=workspace_id)
    chunk_size = 3000  # chars
    chunks = [full_text[i : i + chunk_size] for i in range(0, len(full_text), chunk_size)]

    chunk_summaries = []
    for chunk in chunks[:20]:  # cap at 20 chunks
        try:
            summary = client.generate(
                model=MODEL_HAIKU,
                system="Summarize the following project activity into 2-3 bullet points:",
                user_message=wrap_untrusted(chunk),
                max_tokens=256,
            )
            chunk_summaries.append(summary)
        except Exception as exc:
            logger.warning("_map_reduce_summarize: chunk error — %s", exc)

    return "\n".join(chunk_summaries)
