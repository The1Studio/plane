# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 migration 0003: HNSW index on ai_embeddings.embedding.
#
# Run AFTER the initial backfill is complete (operator step — see RUNBOOK).
# Uses AddIndexConcurrently (atomic=False) so the index build does not lock
# the table for writes during backfill.
#
# Operator instructions:
#   1. Complete the backfill: python manage.py ai_embed_backfill
#   2. Apply this migration: python manage.py migrate ai_ext 0003
#   3. Run: ANALYZE ai_embeddings;

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # MUST be atomic=False for CONCURRENTLY builds.
    atomic = False

    dependencies = [
        ("ai_ext", "0002_ai_embedding"),
    ]

    operations = [
        # HNSW with cosine (l2 distance unused for BGE-M3 dense which is L2-normalized).
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ai_emb_hnsw_idx "
                "ON ai_embeddings USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64);"
            ),
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS ai_emb_hnsw_idx;",
        ),
    ]
