# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 migration 0001: create pgvector extension + AiWorkspaceConfig + AiBatchJob.
# AiEmbedding is in 0002 (depends on pgvector extension being present).

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.contrib.postgres.operations import CreateExtension


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("db", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Enable the pgvector extension (ai_ext owns this — see FORK.md).
        CreateExtension("vector"),

        migrations.CreateModel(
            name="AiWorkspaceConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=False)),
                ("monthly_usd_ceiling", models.FloatField(default=0.0)),
                ("egress_acked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "workspace",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_config",
                        to="db.workspace",
                    ),
                ),
                (
                    "egress_acked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_egress_acks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "AI Workspace Config",
                "verbose_name_plural": "AI Workspace Configs",
                "db_table": "ai_workspace_configs",
            },
        ),

        migrations.CreateModel(
            name="AiBatchJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("batch_id", models.CharField(max_length=128, unique=True)),
                ("job_type", models.CharField(default="digest", max_length=32)),
                ("receivers_map", models.JSONField(default=dict)),
                ("status", models.CharField(default="in_progress", max_length=32)),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_batch_jobs",
                        to="db.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "AI Batch Job",
                "verbose_name_plural": "AI Batch Jobs",
                "db_table": "ai_batch_jobs",
            },
        ),

        migrations.AddIndex(
            model_name="aibatchjob",
            index=models.Index(
                fields=["status", "submitted_at"],
                name="ai_batch_status_submitted_idx",
            ),
        ),
    ]
