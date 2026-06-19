# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload models. New table only — NO column added to core Issue
# (docs/FORK.md DB rule). Mirrors the ai_ext pattern: plain models.Model
# with explicit fields (no ProjectBaseModel.save() coupling).

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .aggregation import MAX_HOURS


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
