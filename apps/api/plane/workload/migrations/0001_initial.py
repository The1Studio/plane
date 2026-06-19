# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload migration 0001 — create the WorkloadEstimate table.
# Lives in this app's own migration graph; never touches plane/db/migrations
# (docs/FORK.md). FK pins to db.0001_initial (Issue/Workspace/Project all
# exist there in the adopted tag).

import uuid

import django.db.models.deletion
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("db", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkloadEstimate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("hours", models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10000)])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "issue",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workload_estimate",
                        to="db.issue",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workload_estimates",
                        to="db.workspace",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workload_estimates",
                        to="db.project",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workload_estimates_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Workload Estimate",
                "verbose_name_plural": "Workload Estimates",
                "db_table": "workload_estimates",
            },
        ),
        migrations.AddIndex(
            model_name="workloadestimate",
            index=models.Index(fields=["project"], name="workload_est_project_idx"),
        ),
    ]
