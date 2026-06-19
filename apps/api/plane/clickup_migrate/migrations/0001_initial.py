# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — initial migration for the clickup_migrate app.
#
# Two things happen here:
#   1. Create this app's own ledger tables (MigrationRun, etc.)
#   2. Add partial unique indexes on core Plane tables for the
#      (external_source='clickup', external_id) pair so the DB
#      enforces idempotency (plan C2). These are ADDITIVE — no
#      core model is edited, no column is added.
#
# The partial-index dependency pins to db migration 0121 (the last
# migration in the adopted tag base v1.3.1) so this migration can
# be rebased cleanly.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    # Set atomic=False so Django does not wrap this migration in a transaction.
    # The ledger CreateModel operations are safe without a transaction (they are
    # idempotent via IF NOT EXISTS at the DB level and Django skips them on replay).
    atomic = False

    # Pin to the last core migration in the adopted tag base (v1.3.1).
    # DO NOT change this to a relative import — explicit name is the rebase anchor.
    dependencies = [
        ("db", "0121_alter_estimate_type"),
    ]

    operations = [
        # ─────────────────────────────────────────────────────────────────
        # Ledger tables
        # ─────────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="MigrationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("space_ids", models.JSONField(default=list)),
                ("dry_run", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("extracting", "Extracting"),
                            ("normalizing", "Normalizing"),
                            ("writing", "Writing"),
                            ("done", "Done"),
                            ("error", "Error"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("error", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "Migration Run",
                "verbose_name_plural": "Migration Runs",
                "db_table": "clickup_migration_runs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MigrationCursor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cursors",
                        to="clickup_migrate.migrationrun",
                    ),
                ),
                ("entity_type", models.CharField(max_length=50)),
                ("container_id", models.CharField(max_length=255)),
                ("cursor_token", models.TextField(blank=True, null=True)),
                ("last_page", models.BooleanField(default=False)),
                ("done", models.BooleanField(default=False)),
            ],
            options={
                "verbose_name": "Migration Cursor",
                "verbose_name_plural": "Migration Cursors",
                "db_table": "clickup_migration_cursors",
            },
        ),
        migrations.AlterUniqueTogether(
            name="migrationcursor",
            unique_together={("run", "entity_type", "container_id")},
        ),
        migrations.CreateModel(
            name="MigrationRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="records",
                        to="clickup_migrate.migrationrun",
                    ),
                ),
                ("source_type", models.CharField(max_length=50)),
                ("source_id", models.CharField(max_length=255)),
                ("plane_type", models.CharField(max_length=50)),
                ("plane_id", models.CharField(blank=True, max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("updated", "Updated"),
                            ("skipped", "Skipped"),
                            ("error", "Error"),
                        ],
                        default="created",
                        max_length=10,
                    ),
                ),
                ("bytes", models.BigIntegerField(default=0)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Migration Record",
                "verbose_name_plural": "Migration Records",
                "db_table": "clickup_migration_records",
            },
        ),
        migrations.AlterUniqueTogether(
            name="migrationrecord",
            unique_together={("run", "source_type", "source_id")},
        ),
        migrations.AddIndex(
            model_name="migrationrecord",
            index=models.Index(fields=["run", "status"], name="cm_record_run_status_idx"),
        ),
        migrations.AddIndex(
            model_name="migrationrecord",
            index=models.Index(fields=["source_type", "source_id"], name="cm_record_src_idx"),
        ),
        migrations.CreateModel(
            name="ClickupCustomFieldArchive",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("issue_external_id", models.CharField(max_length=255, unique=True)),
                ("raw_json", models.JSONField()),
                ("raw_markdown", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "ClickUp Custom Field Archive",
                "verbose_name_plural": "ClickUp Custom Field Archives",
                "db_table": "clickup_custom_field_archives",
            },
        ),
        migrations.CreateModel(
            name="MappingTable",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mappings",
                        to="clickup_migrate.migrationrun",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("status", "Status"),
                            ("priority", "Priority"),
                            ("custom_field", "Custom Field"),
                        ],
                        max_length=20,
                    ),
                ),
                ("source_key", models.TextField()),
                ("target_value", models.TextField(blank=True)),
                ("approved", models.BooleanField(db_index=True, default=False)),
                ("source_meta", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Mapping Table Row",
                "verbose_name_plural": "Mapping Table Rows",
                "db_table": "clickup_mapping_tables",
            },
        ),
        migrations.AlterUniqueTogether(
            name="mappingtable",
            unique_together={("run", "kind", "source_key")},
        ),
        migrations.CreateModel(
            name="EmailCoverage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_coverage",
                        to="clickup_migrate.migrationrun",
                    ),
                ),
                ("clickup_email", models.EmailField()),
                ("plane_user_id", models.CharField(blank=True, max_length=255, null=True)),
                ("signed_off", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Email Coverage Row",
                "verbose_name_plural": "Email Coverage Rows",
                "db_table": "clickup_email_coverage",
            },
        ),
        migrations.AlterUniqueTogether(
            name="emailcoverage",
            unique_together={("run", "clickup_email")},
        ),
        # ─────────────────────────────────────────────────────────────────
        # Partial unique indexes on core tables (additive — no column edits)
        # DB backstop for C2 idempotency. One row per source entity.
        # WHERE clause: external_source='clickup' AND deleted_at IS NULL
        # ─────────────────────────────────────────────────────────────────
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                cu_issue_ext_idx
            ON issues (external_id)
            WHERE external_source = 'clickup' AND deleted_at IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS cu_issue_ext_idx;",
            hints={"target_db": "default"},
        ),
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                cu_project_ext_idx
            ON projects (external_id)
            WHERE external_source = 'clickup' AND deleted_at IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS cu_project_ext_idx;",
        ),
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                cu_state_ext_idx
            ON states (external_id)
            WHERE external_source = 'clickup' AND deleted_at IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS cu_state_ext_idx;",
        ),
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                cu_label_ext_idx
            ON labels (external_id)
            WHERE external_source = 'clickup' AND deleted_at IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS cu_label_ext_idx;",
        ),
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                cu_module_ext_idx
            ON modules (external_id)
            WHERE external_source = 'clickup' AND deleted_at IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS cu_module_ext_idx;",
        ),
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                cu_issue_comment_ext_idx
            ON issue_comments (external_id)
            WHERE external_source = 'clickup' AND deleted_at IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS cu_issue_comment_ext_idx;",
        ),
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                cu_file_asset_ext_idx
            ON file_assets (external_id)
            WHERE external_source = 'clickup' AND deleted_at IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS cu_file_asset_ext_idx;",
        ),
    ]
