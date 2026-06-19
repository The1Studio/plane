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

import django.contrib.postgres.search
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
                # C5 FIX: SearchVectorField so Django migration state matches the
                # real tsvector GENERATED ALWAYS AS STORED column added by RunSQL below.
                # editable=False ensures ORM never names it in INSERT/UPDATE.
                ("tsv", django.contrib.postgres.search.SearchVectorField(editable=False, null=True, blank=True)),
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

        # C5 FIX: Replace the ORM-created tsvector column with a GENERATED ALWAYS AS
        # STORED expression so Postgres computes it automatically on INSERT/UPDATE.
        # The expression indexes content_excerpt (the stored chunk text, up to 512 chars)
        # + entity_type for full-text matching via plainto_tsquery.
        # Django sees SearchVectorField (editable=False) in migration state, which
        # matches the real tsvector column type — no drift.
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
