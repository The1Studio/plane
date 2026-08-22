# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload migration 0006 — the hour cap becomes per-DAY
# (plans/260822-workload-daily-hours, decision D1, resolved with the user
# 2026-08-22).
#
# This is a deliberate DROP-AND-ADD, NOT a RenameField: existing
# `max_weekly_hours` values are DISCARDED rather than converted, and every
# row lands on the new 8.0 daily default. An admin who had customised the
# weekly cap re-enters it once, in the new daily unit, via the workspace
# settings UI. Pre-migration values remain retrievable from a backup:
#
#     SELECT workspace_id, max_weekly_hours FROM workload_settings;
#
# Drop-and-add is what makes the reset explicit and total — a rename followed
# by a data migration would express the same outcome less legibly.
#
# The literals 8.0 and 10000 are HARDCODED below on purpose: a migration is a
# historical record and must not re-derive itself from the live
# DEFAULT_MAX_DAILY_HOURS / MAX_HOURS constants, which will change again.

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workload", "0005_delete_workloadcapacity"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="workloadsettings",
            name="max_weekly_hours",
        ),
        migrations.AddField(
            model_name="workloadsettings",
            name="max_daily_hours",
            field=models.FloatField(
                default=8.0,
                validators=[MinValueValidator(0), MaxValueValidator(10000)],
            ),
        ),
    ]
