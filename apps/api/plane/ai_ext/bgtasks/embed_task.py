# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P4a — Embed-on-write background tasks.
# Runs on the `ai` queue.
# Signals in plane/ai_ext/signals.py call these via transaction.on_commit.

import hashlib
import logging

from celery import shared_task

from plane.ai_ext.clients.bge_client import BGE_EMBED_VERSION, BgeClient
from plane.ai_ext.gate import AiGateError, gate_or_raise

logger = logging.getLogger("plane.ai_ext")

# Approximate token count per chunk target for long pages (~512 tok ≈ 2048 chars).
_CHUNK_CHARS = 2048


def _chunk_text(text: str) -> list[str]:
    """Split text into ~512-token chunks (simple char split)."""
    if not text:
        return []
    return [text[i : i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@shared_task(
    name="plane.ai_ext.bgtasks.embed_task.embed_entity",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def embed_entity(
    self,
    workspace_id: str,
    project_id: str | None,
    entity_type: str,
    entity_id: str,
    text: str | None,
):
    """Embed a single corpus entity and upsert into AiEmbedding.

    Called via transaction.on_commit from signals.py.
    Skips if workspace AI is disabled.  Null/empty text is skipped (no-op).
    Deletes existing chunks for the entity before re-inserting (orphan guard).
    """
    if not text or not text.strip():
        logger.debug("embed_entity: empty text for %s/%s — skip", entity_type, entity_id)
        return

    try:
        gate_or_raise(workspace_id)
    except AiGateError:
        # Workspace AI disabled — skip silently.
        return

    from plane.ai_ext.models import AiEmbedding

    chunks = _chunk_text(text.strip())
    if not chunks:
        return

    bge = BgeClient()
    try:
        embed_results = bge.embed(chunks)
    except Exception as exc:
        logger.exception(
            "embed_entity: BGE sidecar error for %s/%s — %s", entity_type, entity_id, exc
        )
        raise self.retry(exc=exc)
    finally:
        bge.close()

    # Atomic replace: delete all existing chunks then bulk-insert new ones.
    # M3 FIX: drop ignore_conflicts=True from the post-delete insert — after an
    # explicit DELETE there are no conflicts to ignore, and masking IntegrityError
    # here would hide real bugs (e.g. race between two concurrent signal firings).
    # The unique_together constraint on (entity_type, entity_id, chunk_idx) makes
    # a true conflict impossible after a clean delete within the same transaction.
    #
    # C5 FIX: 'tsv' is editable=False (SearchVectorField) so the ORM will NOT
    # include it in the INSERT column list.  Postgres GENERATED ALWAYS AS columns
    # reject any INSERT that names them explicitly — this ensures we never do so.
    import django.db.transaction as _tx
    with _tx.atomic():
        AiEmbedding.objects.filter(entity_type=entity_type, entity_id=entity_id).delete()

        rows = []
        for chunk_idx, (chunk_text, embed_result) in enumerate(zip(chunks, embed_results)):
            rows.append(
                AiEmbedding(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    chunk_idx=chunk_idx,
                    content_hash=_content_hash(chunk_text),
                    content_excerpt=chunk_text[:512],
                    model_id=embed_result.model_id,
                    embed_version=embed_result.embed_version,
                    embedding=embed_result.embedding,
                )
            )
        AiEmbedding.objects.bulk_create(rows, batch_size=100)

    logger.debug(
        "embed_entity: upserted %d chunks for %s/%s", len(rows), entity_type, entity_id
    )


@shared_task(
    name="plane.ai_ext.bgtasks.embed_task.purge_entity_embeddings",
    bind=True,
    max_retries=0,
)
def purge_entity_embeddings(self, entity_type: str, entity_id: str):
    """Delete all embedding chunks for a soft-deleted entity."""
    from plane.ai_ext.models import AiEmbedding

    deleted, _ = AiEmbedding.objects.filter(
        entity_type=entity_type, entity_id=entity_id
    ).delete()
    logger.info("purge_entity_embeddings: deleted %d chunks for %s/%s", deleted, entity_type, entity_id)


@shared_task(
    name="plane.ai_ext.bgtasks.embed_task.purge_workspace_embeddings",
    bind=True,
    max_retries=0,
)
def purge_workspace_embeddings(self, workspace_id: str):
    """Delete all embeddings for a workspace (kill-switch / disable gate).

    Called when a workspace opts out to purge stored vectors.
    """
    from plane.ai_ext.models import AiEmbedding

    deleted, _ = AiEmbedding.objects.filter(workspace_id=workspace_id).delete()
    logger.info("purge_workspace_embeddings: deleted %d chunks for workspace %s", deleted, workspace_id)


@shared_task(
    name="plane.ai_ext.bgtasks.embed_task.restamp_project_embeddings",
    bind=True,
    max_retries=0,
)
def restamp_project_embeddings(self, workspace_id: str, project_id: str):
    """Re-stamp or purge embeddings after ACL change on a project.

    Called when Project.network changes (public/secret flip).
    For simplicity, we re-embed all affected entities so access-checks
    at query time always use live DB filters (embeddings are corpus keys,
    not auth sources).  In practice, only the project row's own embedding
    needs refreshing; issue/page embeddings are filtered live at retrieval.
    """
    from plane.db.models import Project
    try:
        proj = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return

    # Re-embed the project description (access live-filter handles the rest).
    if proj.description:
        embed_entity.delay(
            workspace_id=workspace_id,
            project_id=project_id,
            entity_type="project",
            entity_id=str(project_id),
            text=proj.description,
        )
