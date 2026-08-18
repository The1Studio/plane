# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload migration 0003 — create the WorkloadSettings table (workspace-wide
# work configuration: max weekly hours, workdays, week start day).
# Lives in this app's own migration graph; never touches plane/db/migrations
# (docs/FORK.md). FK pins to db's latest migration in the adopted tag, which
# already has Workspace.

import uuid

import django.contrib.postgres.fields
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import plane.workload.models


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0121_alter_estimate_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("workload", "0002_workloadcapacity"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkloadSettings",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "max_weekly_hours",
                    models.FloatField(
                        default=40.0,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(10000),
                        ],
                    ),
                ),
                (
                    "workdays",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.PositiveSmallIntegerField(),
                        default=plane.workload.models.default_workdays,
                        size=None,
                    ),
                ),
                ("week_start_day", models.PositiveSmallIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workload_settings_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workload_settings",
                        to="db.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "Workload Settings",
                "verbose_name_plural": "Workload Settings",
                "db_table": "workload_settings",
            },
        ),
        migrations.AddConstraint(
            model_name="workloadsettings",
            constraint=models.CheckConstraint(
                check=models.Q(("week_start_day__gte", 0), ("week_start_day__lte", 6)),
                name="ck_workload_settings_week_start_day_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="workloadsettings",
            constraint=models.CheckConstraint(
                check=models.Q(("workdays__len__gt", 0)),
                name="ck_workload_settings_workdays_nonempty",
            ),
        ),
    ]
