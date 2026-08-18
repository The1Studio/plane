# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload models. New table only — NO column added to core Issue
# (docs/FORK.md DB rule). Mirrors the ai_ext pattern: plain models.Model
# with explicit fields (no ProjectBaseModel.save() coupling).

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

# MAX_HOURS is imported from constants.py directly (the leaf module) rather
# than re-exported through aggregation.py — models.py has no reason to reach
# into the aggregation module for a value that lives one hop closer.
from .constants import DEFAULT_MAX_WEEKLY_HOURS, DEFAULT_WEEK_START_DAY, DEFAULT_WORKDAYS, MAX_HOURS


def default_workdays():
    """Module-level callable default for WorkloadSettings.workdays.

    MUST be a callable, never a mutable list literal passed directly as
    `default=[1, 2, 3, 4, 5]` — Django would share ONE list instance across
    every model instantiation (the classic mutable-default footgun) and
    `makemigrations` serializes a bare list default incorrectly. Returning a
    fresh copy of DEFAULT_WORKDAYS on every call avoids both.
    """
    return list(DEFAULT_WORKDAYS)


class WorkloadEstimate(models.Model):
    """Per-issue time estimate, in hours.

    One estimate per issue (OneToOne). Free numeric hours (quantized to 2
    decimals on write). The table only ever holds estimated issues, so it
    is inherently the small/selective set the workload query drives from.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.OneToOneField(
        "db.Issue",
        on_delete=models.CASCADE,
        related_name="workload_estimate",
    )
    # Denormalized scoping FKs (mirror ai_ext) — cheap filters, kept in sync
    # by the write path which always sets them from the issue.
    workspace = models.ForeignKey(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="workload_estimates",
    )
    project = models.ForeignKey(
        "db.Project",
        on_delete=models.CASCADE,
        related_name="workload_estimates",
    )
    hours = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(MAX_HOURS)])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workload_estimates_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workload_estimates"
        verbose_name = "Workload Estimate"
        verbose_name_plural = "Workload Estimates"
        indexes = [models.Index(fields=["project"], name="workload_est_project_idx")]

    def __str__(self):
        return f"WorkloadEstimate(issue={self.issue_id}, hours={self.hours})"


class WorkloadSettings(models.Model):
    """Workspace-wide work configuration: max weekly hours, workdays, week start.

    Replaces the per-member WorkloadCapacity grain (deleted in Phase 3). One
    row per workspace; a workspace with NO row reads the constants.py
    defaults — see views.py, which never calls get_or_create on a GET.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="workload_settings",
    )
    max_weekly_hours = models.FloatField(
        default=DEFAULT_MAX_WEEKLY_HOURS,
        validators=[MinValueValidator(0), MaxValueValidator(MAX_HOURS)],
    )
    # Plane's EStartOfTheWeek encoding: SUNDAY=0 .. SATURDAY=6 (constants.py).
    workdays = ArrayField(
        models.PositiveSmallIntegerField(),
        default=default_workdays,
    )
    week_start_day = models.PositiveSmallIntegerField(default=DEFAULT_WEEK_START_DAY)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workload_settings_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workload_settings"
        verbose_name = "Workload Settings"
        verbose_name_plural = "Workload Settings"
        constraints = [
            models.CheckConstraint(
                check=Q(week_start_day__gte=0) & Q(week_start_day__lte=6),
                name="ck_workload_settings_week_start_day_range",
            ),
            # Backstop for the divide-by-zero an empty workdays array would
            # cause in aggregation.py — the serializer also rejects an empty
            # list, but this constraint holds even for a row written outside
            # the serializer (admin, data migration, direct ORM use).
            models.CheckConstraint(
                check=Q(workdays__len__gt=0),
                name="ck_workload_settings_workdays_nonempty",
            ),
        ]

    def __str__(self):
        return f"WorkloadSettings(workspace={self.workspace_id}, max_weekly_hours={self.max_weekly_hours})"
