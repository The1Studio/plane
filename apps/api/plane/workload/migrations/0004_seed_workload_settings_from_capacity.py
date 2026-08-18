# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload migration 0004 — data migration, first of two steps that retire
# the per-member WorkloadCapacity grain in favour of workspace-wide
# WorkloadSettings (plan D1, phase-3.md). MUST land before the DeleteModel
# migration that follows it (0005): once WorkloadCapacity is dropped there is
# nothing left here to read the seed set from.
#
# Per D8, existing per-member `weekly_hours` values are intentionally NOT
# read. The live database holds exactly one WorkloadCapacity row and it is a
# placeholder `0` — a max()-derived seed would render every member
# "over capacity" the instant this migration lands. Every eligible workspace
# instead gets the SAME fixed default (40h / Mon-Fri / Monday-start), which
# an admin can adjust once via the Phase 1 PUT endpoint.
#
# The literal default values below intentionally MIRROR (rather than import)
# plane/workload/constants.py's DEFAULT_MAX_WEEKLY_HOURS / DEFAULT_WORKDAYS /
# DEFAULT_WEEK_START_DAY — a data migration's behaviour must stay pinned to
# what shipped the day it ran, independent of whatever constants.py says on
# a LATER checkout. (0003_workloadsettings.py imports plane.workload.models
# for a *schema* default only — a different, narrower case: Django needs the
# actual callable there to serialize the field's `default=`, and that
# callable's own body is what is frozen into the migration state.)

from django.db import migrations

DEFAULT_MAX_WEEKLY_HOURS = 40.0
DEFAULT_WORKDAYS = [1, 2, 3, 4, 5]  # Mon-Fri, Plane's EStartOfTheWeek encoding
DEFAULT_WEEK_START_DAY = 1  # Monday


def seed_default_settings_for_capacity_workspaces(apps, schema_editor):
    """For every workspace that has WorkloadCapacity rows but no
    WorkloadSettings row yet, create one with the fixed default. Workspaces
    that already have a settings row (e.g. from a Phase 1 PUT landing before
    this migration ran) are left untouched — never overwritten."""
    WorkloadCapacity = apps.get_model("workload", "WorkloadCapacity")
    WorkloadSettings = apps.get_model("workload", "WorkloadSettings")

    capacity_workspace_ids = set(
        WorkloadCapacity.objects.values_list("workspace_id", flat=True).distinct()
    )
    if not capacity_workspace_ids:
        return

    existing_settings_workspace_ids = set(
        WorkloadSettings.objects.filter(
            workspace_id__in=capacity_workspace_ids
        ).values_list("workspace_id", flat=True)
    )
    missing_workspace_ids = capacity_workspace_ids - existing_settings_workspace_ids

    WorkloadSettings.objects.bulk_create(
        [
            WorkloadSettings(
                workspace_id=workspace_id,
                max_weekly_hours=DEFAULT_MAX_WEEKLY_HOURS,
                workdays=list(DEFAULT_WORKDAYS),
                week_start_day=DEFAULT_WEEK_START_DAY,
            )
            for workspace_id in missing_workspace_ids
        ]
    )


def unseed_default_settings_for_capacity_workspaces(apps, schema_editor):
    """Reverse of the above — a REAL reverse, not RunPython.noop.

    Deletes only WorkloadSettings rows that (a) belong to a workspace that
    still has WorkloadCapacity rows at reversal time, AND (b) still hold
    EXACTLY the seeded default values untouched. A workspace an admin has
    since edited via the Phase 1 PUT endpoint (any field differs from the
    seeded default) is left alone — this migration must never delete real
    admin configuration, even at the cost of leaving an indistinguishable
    "admin deliberately chose the default" row behind on reversal. Per-member
    WorkloadCapacity.weekly_hours values are NOT restored by this reverse (or
    by any migration) — see 0005's docstring for why that data is gone for
    good once the removal migration after this one has run.
    """
    WorkloadCapacity = apps.get_model("workload", "WorkloadCapacity")
    WorkloadSettings = apps.get_model("workload", "WorkloadSettings")

    capacity_workspace_ids = set(
        WorkloadCapacity.objects.values_list("workspace_id", flat=True).distinct()
    )
    if not capacity_workspace_ids:
        return

    WorkloadSettings.objects.filter(
        workspace_id__in=capacity_workspace_ids,
        max_weekly_hours=DEFAULT_MAX_WEEKLY_HOURS,
        workdays=DEFAULT_WORKDAYS,
        week_start_day=DEFAULT_WEEK_START_DAY,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workload", "0003_workloadsettings"),
    ]

    operations = [
        migrations.RunPython(
            seed_default_settings_for_capacity_workspaces,
            reverse_code=unseed_default_settings_for_capacity_workspaces,
        ),
    ]
