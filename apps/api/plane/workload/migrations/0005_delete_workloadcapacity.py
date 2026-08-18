# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload migration 0005 — second of two steps that retire the per-member
# WorkloadCapacity grain (plan D1, phase-3.md). MUST run after 0004, which
# seeds a WorkloadSettings row for every workspace this table's data would
# otherwise leave with no effective capacity config.
#
# Reversing this migration (`manage.py migrate workload 0004`) recreates an
# EMPTY workload_capacities table — Django's standard DeleteModel reversal
# restores the table's SCHEMA (columns, FKs, constraints) from migration
# state, never the ROWS it held; those were destroyed the moment this
# migration's forward operation ran. Per-member `weekly_hours` values are
# NOT restorable by this migration, by 0004's reverse, or by any other
# migration in this app — the only surviving record of the discarded values
# is the `SELECT * FROM workload_capacities` dump captured in this feature's
# PR description before merge (see phase-3.md).
#
# Operations below are UNEDITED output of `manage.py makemigrations workload`
# run against the model state after WorkloadCapacity was removed from
# models.py — Django's autodetector determined a bare DeleteModel is
# sufficient (it folds the model's two UniqueConstraints into the same
# operation; no separate RemoveConstraint step is needed), so this matches
# exactly what `makemigrations --check --dry-run` expects.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workload", "0004_seed_workload_settings_from_capacity"),
    ]

    operations = [
        migrations.DeleteModel(
            name="WorkloadCapacity",
        ),
    ]
