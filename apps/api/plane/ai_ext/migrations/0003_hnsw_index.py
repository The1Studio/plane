# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 migration 0003: HNSW index on ai_embeddings.embedding.
#
# Run AFTER the initial backfill is complete (operator step — see RUNBOOK).
# Uses atomic=False + RunSQL with CONCURRENTLY so the index build does not
# lock the table for writes.
#
# C6 FIX: the original RunSQL used "CREATE INDEX CONCURRENTLY IF NOT EXISTS".
# A failed HNSW build leaves the index in INVALID state; "IF NOT EXISTS" then
# silently skips re-creation forever, leaving the INVALID index in place.
# Fixed by:
#   1. A pre-step that DROPs any pre-existing INVALID index with that name.
#   2. Creating the index WITHOUT "IF NOT EXISTS" so a second partial failure
#      is surfaced rather than silently skipped.
#
# Operator instructions:
#   1. Complete the backfill: python manage.py ai_embed_backfill
#   2. Apply this migration: python manage.py migrate ai_ext 0003
#   3. Run: ANALYZE ai_embeddings;
#   4. If the migration fails, check pg_indexes WHERE indexname = 'ai_emb_hnsw_idx'
#      for indisvalid=false; re-run migrate ai_ext 0003 after fixing the cause.

from django.db import migrations


class Migration(migrations.Migration):
    # MUST be atomic=False for CONCURRENTLY builds.
    atomic = False

    dependencies = [
        ("ai_ext", "0002_ai_embedding"),
    ]

    operations = [
        # Step 1: Drop any INVALID index left by a previous failed CONCURRENTLY build.
        # An index is INVALID when pg_index.indisvalid = false; a valid index is
        # never dropped here — the DROP is a no-op if the index doesn't exist or
        # is already valid and complete (the WHERE clause guards that).
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM   pg_class c
                    JOIN   pg_index i ON i.indexrelid = c.oid
                    WHERE  c.relname = 'ai_emb_hnsw_idx'
                    AND    NOT i.indisvalid
                ) THEN
                    DROP INDEX CONCURRENTLY IF EXISTS ai_emb_hnsw_idx;
                END IF;
            END
            $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Step 2: Build the HNSW index.  No "IF NOT EXISTS" so a second failure
        # raises an error instead of silently skipping.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY ai_emb_hnsw_idx "
                "ON ai_embeddings USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64);"
            ),
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS ai_emb_hnsw_idx;",
        ),
    ]
