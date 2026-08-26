# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P4a management command: resumable BGE-M3 backfill.
# Embeds into the unindexed table; HNSW index is built separately (0003).
# Throttled to keep Postgres CPU ≤50% (configurable --sleep-ms).

import hashlib
import logging
import time

from django.core.management.base import BaseCommand
from django.db.models import Q

logger = logging.getLogger("plane.ai_ext")


class Command(BaseCommand):
    help = "Backfill BGE-M3 embeddings for all existing Plane content (resumable)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-slug",
            type=str,
            default=None,
            help="Limit backfill to a single workspace slug.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Number of entities per BGE batch call (default: 50).",
        )
        parser.add_argument(
            "--sleep-ms",
            type=int,
            default=200,
            help="Milliseconds to sleep between batches (throttle, default: 200).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print counts only; do not write any embeddings.",
        )

    def handle(self, *args, **options):
        from plane.db.models import (
            Workspace,
        )
        from plane.ai_ext.clients.bge_client import BgeClient

        workspace_slug = options["workspace_slug"]
        batch_size = options["batch_size"]
        sleep_sec = options["sleep_ms"] / 1000.0
        dry_run = options["dry_run"]

        workspaces_qs = Workspace.objects.all()
        if workspace_slug:
            workspaces_qs = workspaces_qs.filter(slug=workspace_slug)

        bge = BgeClient()
        total_embedded = 0

        for workspace in workspaces_qs:
            self.stdout.write(f"[backfill] Workspace: {workspace.slug} ({workspace.id})")

            # Check AI is enabled for this workspace.
            from plane.ai_ext.models import AiWorkspaceConfig
            config, _ = AiWorkspaceConfig.get_or_create_for(workspace.id)
            if not config.enabled:
                self.stdout.write(f"  [skip] AI not enabled for {workspace.slug}")
                continue

            # Entity types to backfill.
            entities = [
                ("issue", self._issue_texts(workspace.id)),
                ("issue_comment", self._comment_texts(workspace.id)),
                ("page", self._page_texts(workspace.id)),
                ("cycle", self._cycle_texts(workspace.id)),
                ("module", self._module_texts(workspace.id)),
                ("project", self._project_texts(workspace.id)),
            ]

            for entity_type, qs in entities:
                count = qs.count()
                self.stdout.write(f"  [{entity_type}] {count} entities")
                if dry_run:
                    continue

                batch = []
                for row in qs.iterator(chunk_size=batch_size):
                    batch.append(row)
                    if len(batch) >= batch_size:
                        self._embed_batch(bge, workspace, entity_type, batch, dry_run)
                        total_embedded += len(batch)
                        batch = []
                        time.sleep(sleep_sec)

                if batch:
                    self._embed_batch(bge, workspace, entity_type, batch, dry_run)
                    total_embedded += len(batch)

        bge.close()
        self.stdout.write(self.style.SUCCESS(f"[backfill] Done. Total embedded: {total_embedded}"))

    # ------------------------------------------------------------------
    # Entity querysets (returning dicts with id, project_id, text)
    # ------------------------------------------------------------------

    def _issue_texts(self, workspace_id):
        from plane.db.models import Issue
        return (
            Issue.issue_objects.filter(workspace_id=workspace_id, deleted_at__isnull=True)
            .exclude(Q(name__isnull=True) & Q(description_stripped__isnull=True))
            .values("id", "project_id", "name", "description_stripped")
        )

    def _comment_texts(self, workspace_id):
        from plane.db.models import IssueComment
        return (
            IssueComment.objects.filter(
                workspace_id=workspace_id,
                deleted_at__isnull=True,
            )
            .exclude(comment_stripped="")
            .values("id", "project_id", "comment_stripped")
        )

    def _page_texts(self, workspace_id):
        from plane.db.models import Page
        return (
            Page.objects.filter(workspace_id=workspace_id, deleted_at__isnull=True)
            .exclude(description_stripped__isnull=True)
            .values("id", "description_stripped")
        )

    def _cycle_texts(self, workspace_id):
        from plane.db.models import Cycle
        return (
            Cycle.objects.filter(workspace_id=workspace_id, deleted_at__isnull=True)
            .exclude(description__isnull=True)
            .values("id", "project_id", "description")
        )

    def _module_texts(self, workspace_id):
        from plane.db.models import Module
        return (
            Module.objects.filter(workspace_id=workspace_id, deleted_at__isnull=True)
            .exclude(description__isnull=True)
            .values("id", "project_id", "description")
        )

    def _project_texts(self, workspace_id):
        from plane.db.models import Project
        return (
            Project.objects.filter(workspace_id=workspace_id)
            .exclude(description__isnull=True)
            .values("id", "description")
        )

    # ------------------------------------------------------------------
    # Batch embed + upsert
    # ------------------------------------------------------------------

    def _embed_batch(self, bge, workspace, entity_type, rows, dry_run):
        from plane.ai_ext.models import AiEmbedding
        # model_id and embed_version are read from embed_result (env-driven via BgeClient).

        # Map text field name by entity type.
        _TEXT_FIELD = {
            "issue": lambda r: " ".join(filter(None, [r.get("name"), r.get("description_stripped")])),
            "issue_comment": lambda r: r.get("comment_stripped", ""),
            "page": lambda r: r.get("description_stripped", ""),
            "cycle": lambda r: r.get("description", ""),
            "module": lambda r: r.get("description", ""),
            "project": lambda r: r.get("description", ""),
        }
        text_fn = _TEXT_FIELD[entity_type]

        texts = [text_fn(r) for r in rows]
        # Filter out empty.
        valid = [(r, t) for r, t in zip(rows, texts) if t and t.strip()]
        if not valid:
            return

        rows_valid, texts_valid = zip(*valid)

        try:
            embed_results = bge.embed(list(texts_valid))
        except Exception as exc:
            self.stderr.write(f"  [error] BGE batch failed for {entity_type}: {exc}")
            return

        to_create = []
        for row, embed_result in zip(rows_valid, embed_results):
            entity_id = str(row["id"])
            project_id = row.get("project_id")
            text = text_fn(row)
            content_hash = hashlib.sha256(text.encode()).hexdigest()

            # Skip if content_hash unchanged (incremental).
            existing = AiEmbedding.objects.filter(
                entity_type=entity_type,
                entity_id=entity_id,
                chunk_idx=0,
                content_hash=content_hash,
            ).exists()
            if existing:
                continue

            # Delete stale chunks before re-insert.
            AiEmbedding.objects.filter(entity_type=entity_type, entity_id=entity_id).delete()

            to_create.append(
                AiEmbedding(
                    workspace_id=workspace.id,
                    project_id=project_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    chunk_idx=0,
                    content_hash=content_hash,
                    content_excerpt=text[:512],
                    model_id=embed_result.model_id,
                    embed_version=embed_result.embed_version,
                    embedding=embed_result.embedding,
                )
            )

        if to_create:
            AiEmbedding.objects.bulk_create(to_create, batch_size=100, ignore_conflicts=True)
            self.stdout.write(f"    embedded {len(to_create)} {entity_type} chunks")
