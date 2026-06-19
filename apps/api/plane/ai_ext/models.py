# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 AI extension models. All new tables live here — no edits to core
# plane/db/models/ (fork isolation, docs/FORK.md).

import uuid

from django.db import models
from pgvector.django import VectorField  # type: ignore[import]

try:
    from django.contrib.postgres.search import SearchVectorField  # Django ≥ 3.1
    _HAS_SEARCH_VECTOR_FIELD = True
except ImportError:  # pragma: no cover
    SearchVectorField = None
    _HAS_SEARCH_VECTOR_FIELD = False


class AiWorkspaceConfig(models.Model):
    """Per-workspace opt-in gate for all AI features (SP2 decision A2).

    Lazy-created via get_or_create so every check is NPE-safe.  Default
    is disabled so no workspace egresses data without explicit sign-off.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_config",
    )
    # Feature flag: AI features only activate when True.
    enabled = models.BooleanField(default=False)
    # Monthly spend ceiling in USD (Decimal-safe float); 0 = no ceiling.
    monthly_usd_ceiling = models.FloatField(default=0.0)
    # Egress acknowledgment — workspace admin who signed off data-flow doc.
    egress_acked_by = models.ForeignKey(
        "db.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_egress_acks",
    )
    egress_acked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_workspace_configs"
        verbose_name = "AI Workspace Config"
        verbose_name_plural = "AI Workspace Configs"

    def __str__(self):
        return f"AiConfig({self.workspace_id}, enabled={self.enabled})"

    @classmethod
    def get_or_create_for(cls, workspace_id):
        """Return (config, created).  Never raises even if workspace_id is
        invalid — callers should check config.enabled themselves."""
        obj, created = cls.objects.get_or_create(workspace_id=workspace_id)
        return obj, created


class AiEmbedding(models.Model):
    """Dense vector embedding for a Plane corpus chunk (BGE-M3, 1024-dim).

    One row per chunk.  A single entity (e.g. long Page) may have multiple
    chunks (chunk_idx 0, 1, 2 …).

    Index notes:
    - GIN on tsv for lexical search (created in migration 0002).
    - B-tree on (workspace_id, project_id) for pre-filter scans.
    - HNSW on embedding built AFTER backfill via AddIndexConcurrently
      (migration 0003, atomic=False) — building inline on a large table locks
      writes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_embeddings",
        db_index=False,  # covered by compound B-tree in migration
    )
    project = models.ForeignKey(
        "db.Project",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_embeddings",
        db_index=False,
    )
    # Corpus entity type: "issue", "issue_comment", "page", "cycle", "module", "project"
    entity_type = models.CharField(max_length=64)
    entity_id = models.UUIDField()
    # Zero-based chunk index within the entity.
    chunk_idx = models.PositiveSmallIntegerField(default=0)
    # SHA-256 of the chunk text — used for incremental re-embedding.
    content_hash = models.CharField(max_length=64)
    # Plain-text excerpt of the chunk (first 512 chars) — feeds the tsv
    # GENERATED column for lexical search.  Storing the excerpt avoids a
    # JOIN back to the source table at retrieval time.
    content_excerpt = models.TextField(blank=True, default="")
    # BGE-M3 model identifier stored for future migration safety.
    model_id = models.CharField(max_length=128)
    embed_version = models.CharField(max_length=32, default="1")
    # Dense embedding vector — dim enforced by BGE client assert.
    embedding = VectorField(dimensions=1024)
    # Full-text search tsvector — GENERATED ALWAYS AS STORED (migration 0002).
    #
    # C5 FIX: declared as SearchVectorField(editable=False) so:
    #   (a) Django migration state matches the real Postgres column type (tsvector
    #       vs the old TextField drift that caused migration disagreement).
    #   (b) bulk_create MUST NOT include 'tsv' in the field list — Postgres
    #       rejects any INSERT that names a GENERATED ALWAYS column.
    #       All callers use AiEmbedding(...) without setting tsv, so the ORM
    #       will not include it in INSERT by default (editable=False + no default
    #       means it's omitted from the SQL unless explicitly listed).
    #
    # The GENERATED expression in migration 0002 uses the full content_excerpt
    # text (not capped at 512 — the cap was on content_excerpt itself, which is
    # fine; tsv is generated from the full stored content_excerpt value).
    tsv = (SearchVectorField if _HAS_SEARCH_VECTOR_FIELD else models.TextField)(
        editable=False, null=True, blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_embeddings"
        verbose_name = "AI Embedding"
        verbose_name_plural = "AI Embeddings"
        # Compound uniqueness: one chunk-idx per entity.
        unique_together = [("entity_type", "entity_id", "chunk_idx")]
        indexes = [
            # Compound B-tree used by the workspace/project pre-filter.
            models.Index(fields=["workspace_id", "project_id"], name="ai_emb_ws_proj_idx"),
        ]

    def __str__(self):
        return f"AiEmbedding({self.entity_type}/{self.entity_id}:{self.chunk_idx})"


class AiBatchJob(models.Model):
    """Tracks an Anthropic Batch API submission for digest fan-out (P3).

    T1 creates the batch + this row.  T2 (beat poller ~10 min) queries
    Anthropic for ended batches, maps custom_id → receiver, fans out.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_batch_jobs",
    )
    # Anthropic Batch API id (e.g. "batch_01…")
    batch_id = models.CharField(max_length=128, unique=True)
    # "digest" or "eval" — discriminator for the poller fan-out.
    job_type = models.CharField(max_length=32, default="digest")
    # JSON: {custom_id: {receiver_id, entity_type, entity_id, …}}
    receivers_map = models.JSONField(default=dict)
    # Status mirrored from Anthropic: "in_progress", "ended", "expired", "canceling", "canceled"
    status = models.CharField(max_length=32, default="in_progress")
    submitted_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_batch_jobs"
        verbose_name = "AI Batch Job"
        verbose_name_plural = "AI Batch Jobs"
        indexes = [
            models.Index(fields=["status", "submitted_at"], name="ai_batch_status_submitted_idx"),
        ]

    def __str__(self):
        return f"AiBatchJob({self.batch_id}, {self.status})"
