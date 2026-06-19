# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 migration 0002: AiEmbedding table + GIN(tsv) + B-tree(workspace,project).
# The tsvector column is GENERATED ALWAYS AS STORED via raw SQL (Django
# VectorField doesn't model GENERATED columns — we use RunSQL).
# HNSW index is deferred to migration 0003 (built AFTER backfill,
# AddIndexConcurrently, atomic=False to avoid table lock).

import uuid

import django.db.models.deletion
from django.db import migrations, models
from pgvector.django import VectorField


class Migration(migrations.Migration):

    dependencies = [
        ("ai_ext", "0001_initial"),
        ("db", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AiEmbedding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("entity_type", models.CharField(max_length=64)),
                ("entity_id", models.UUIDField()),
                ("chunk_idx", models.PositiveSmallIntegerField(default=0)),
                ("content_hash", models.CharField(max_length=64)),
                ("model_id", models.CharField(max_length=128)),
                ("embed_version", models.CharField(default="1", max_length=32)),
                # pgvector VectorField — dim=1024, BGE-M3 dense.
                ("embedding", VectorField(dimensions=1024)),
                # Plain-text excerpt (first 512 chars) used to populate tsv.
                ("content_excerpt", models.TextField(blank=True, default="")),
                # tsv placeholder — real expression is added via RunSQL below.
                ("tsv", models.TextField(blank=True, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "workspace",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_embeddings",
                        to="db.workspace",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_embeddings",
                        to="db.project",
                    ),
                ),
            ],
            options={
                "verbose_name": "AI Embedding",
                "verbose_name_plural": "AI Embeddings",
                "db_table": "ai_embeddings",
            },
        ),

        migrations.AlterUniqueTogether(
            name="aiembedding",
            unique_together={("entity_type", "entity_id", "chunk_idx")},
        ),

        # Compound B-tree for workspace/project pre-filter scans.
        migrations.AddIndex(
            model_name="aiembedding",
            index=models.Index(
                fields=["workspace_id", "project_id"],
                name="ai_emb_ws_proj_idx",
            ),
        ),

        # Convert the tsv column to GENERATED ALWAYS AS (entity_type || ' ' || entity_id::text)
        # using 'simple' configuration.  We generate from content_hash as a proxy because
        # we don't store raw text in the row — real full-text indexing on stored chunk text
        # is handled by re-embedding on write.  The GENERATED column expression uses
        # to_tsvector over model_id + entity_type (stable, always non-null).
        # Actual text content goes through BM25-style approximate matching via
        # plainto_tsquery against this column.
        # NOTE: the tsv column is updated via trigger in production; here we use the
        # closest portable approximation.
        migrations.RunSQL(
            sql="""
            ALTER TABLE ai_embeddings
            DROP COLUMN tsv;

            ALTER TABLE ai_embeddings
            ADD COLUMN tsv tsvector
            GENERATED ALWAYS AS (
                to_tsvector('simple', coalesce(content_excerpt, '') || ' ' || entity_type)
            ) STORED;
            """,
            reverse_sql="""
            ALTER TABLE ai_embeddings DROP COLUMN tsv;
            ALTER TABLE ai_embeddings ADD COLUMN tsv text DEFAULT '' NOT NULL;
            """,
        ),

        # GIN index on the generated tsv column for fast full-text queries.
        migrations.RunSQL(
            sql="CREATE INDEX ai_emb_tsv_gin_idx ON ai_embeddings USING GIN(tsv);",
            reverse_sql="DROP INDEX IF EXISTS ai_emb_tsv_gin_idx;",
        ),
    ]
