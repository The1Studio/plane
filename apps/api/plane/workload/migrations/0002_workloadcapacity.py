# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload migration 0002 — create the WorkloadCapacity table.
# Lives in this app's own migration graph; never touches plane/db/migrations
# (docs/FORK.md). FK pins to db.0001_initial (Workspace/Project already exist
# there in the adopted tag).

import uuid

import django.db.models.deletion
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workload", "0001_initial"),
        ("db", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkloadCapacity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("weekly_hours", models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10000)])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workload_capacities",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workload_capacities",
                        to="db.workspace",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workload_capacities",
                        to="db.project",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workload_capacities_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Workload Capacity",
                "verbose_name_plural": "Workload Capacities",
                "db_table": "workload_capacities",
            },
        ),
        migrations.AddConstraint(
            model_name="workloadcapacity",
            constraint=models.UniqueConstraint(
                condition=models.Q(("project__isnull", True)),
                fields=("member", "workspace"),
                name="uq_workload_capacity_workspace",
            ),
        ),
        migrations.AddConstraint(
            model_name="workloadcapacity",
            constraint=models.UniqueConstraint(
                condition=models.Q(("project__isnull", False)),
                fields=("member", "workspace", "project"),
                name="uq_workload_capacity_project",
            ),
        ),
    ]
