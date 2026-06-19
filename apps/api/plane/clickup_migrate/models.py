# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — ClickUp → Plane migration ledger models.
# Lives in the clickup_migrate app (self-contained per docs/FORK.md).

from django.db import models


class MigrationRun(models.Model):
    """Top-level record for a single migration execution."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    space_ids = models.JSONField(
        default=list,
        help_text="ClickUp space IDs included in this run (empty = all)",
    )
    dry_run = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=(
            ("pending", "Pending"),
            ("extracting", "Extracting"),
            ("normalizing", "Normalizing"),
            ("writing", "Writing"),
            ("done", "Done"),
            ("error", "Error"),
        ),
        default="pending",
    )
    error = models.TextField(blank=True)
    notes = models.TextField(blank=True, help_text="Operator notes")

    class Meta:
        db_table = "clickup_migration_runs"
        ordering = ("-created_at",)
        verbose_name = "Migration Run"
        verbose_name_plural = "Migration Runs"

    def __str__(self):
        return f"MigrationRun #{self.pk} ({self.status})"


class MigrationCursor(models.Model):
    """Resumable per-entity cursor.

    cursor_token is opaque: holds ClickUp start_id for comment paging
    or pass-2 progress markers. Keeping it as TEXT lets us store any
    paging token without a schema migration when ClickUp changes its
    cursor format.
    """

    run = models.ForeignKey(
        MigrationRun,
        on_delete=models.CASCADE,
        related_name="cursors",
    )
    entity_type = models.CharField(
        max_length=50,
        help_text="E.g. 'tasks', 'comments', 'relations'",
    )
    container_id = models.CharField(
        max_length=255,
        help_text="ClickUp list/space/task id scoping this cursor",
    )
    # Opaque: ClickUp start_id for comments; page-number string for task pages.
    cursor_token = models.TextField(null=True, blank=True)
    last_page = models.BooleanField(default=False)
    done = models.BooleanField(default=False)

    class Meta:
        db_table = "clickup_migration_cursors"
        unique_together = [("run", "entity_type", "container_id")]
        verbose_name = "Migration Cursor"
        verbose_name_plural = "Migration Cursors"

    def __str__(self):
        return f"{self.entity_type}/{self.container_id} (run={self.run_id})"


class MigrationRecord(models.Model):
    """Atomic ledger entry: one row per source entity written to Plane.

    status values:
      created  — first write succeeded
      updated  — idempotent re-run updated an existing row
      skipped  — ledger says already done and plane_id still exists
      error    — write failed; error field has details

    bytes is non-zero only for ISSUE_ATTACHMENT records.
    """

    STATUS_CREATED = "created"
    STATUS_UPDATED = "updated"
    STATUS_SKIPPED = "skipped"
    STATUS_ERROR = "error"
    STATUS_CHOICES = (
        (STATUS_CREATED, "Created"),
        (STATUS_UPDATED, "Updated"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_ERROR, "Error"),
    )

    run = models.ForeignKey(
        MigrationRun,
        on_delete=models.CASCADE,
        related_name="records",
    )
    source_type = models.CharField(
        max_length=50,
        help_text="ClickUp entity type, e.g. 'task', 'comment', 'attachment'",
    )
    source_id = models.CharField(max_length=255, help_text="ClickUp entity id")
    plane_type = models.CharField(
        max_length=50,
        help_text="Plane model name, e.g. 'Issue', 'IssueComment'",
    )
    plane_id = models.CharField(max_length=255, blank=True, help_text="Plane pk (UUID as string)")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_CREATED)
    bytes = models.BigIntegerField(default=0, help_text="Bytes transferred (attachments only)")
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clickup_migration_records"
        unique_together = [("run", "source_type", "source_id")]
        indexes = [
            models.Index(fields=["run", "status"]),
            models.Index(fields=["source_type", "source_id"]),
        ]
        verbose_name = "Migration Record"
        verbose_name_plural = "Migration Records"

    def __str__(self):
        return f"{self.source_type}/{self.source_id} → {self.plane_type}/{self.plane_id}"


class ClickupCustomFieldArchive(models.Model):
    """Raw custom-field JSON + computed Markdown for every ClickUp task.

    Retained post-migration as the lossless archive (M1 decision).
    issue_external_id is the ClickUp task id; no FK to Issue to avoid
    cascade-delete losing the archive if an issue is later deleted.
    """

    issue_external_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="ClickUp task id",
    )
    raw_json = models.JSONField(help_text="Raw custom_fields array from ClickUp")
    raw_markdown = models.TextField(
        blank=True,
        help_text="Rendered Markdown table appended to description",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clickup_custom_field_archives"
        verbose_name = "ClickUp Custom Field Archive"
        verbose_name_plural = "ClickUp Custom Field Archives"

    def __str__(self):
        return f"CustomField archive task={self.issue_external_id}"


class MappingTable(models.Model):
    """Human-approved mapping from ClickUp values to Plane equivalents.

    For statuses: source_key = JSON-encoded (list_id, status_name) tuple
    (NOT bare status name — the same name can map differently across lists).
    For priorities: source_key = ClickUp priority string.
    For custom-field render formats: source_key = field_id.

    approved must be True for every row before --apply is permitted.
    """

    KIND_STATUS = "status"
    KIND_PRIORITY = "priority"
    KIND_CUSTOM_FIELD = "custom_field"
    KIND_CHOICES = (
        (KIND_STATUS, "Status"),
        (KIND_PRIORITY, "Priority"),
        (KIND_CUSTOM_FIELD, "Custom Field"),
    )

    run = models.ForeignKey(
        MigrationRun,
        on_delete=models.CASCADE,
        related_name="mappings",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    # JSON-encoded composite key for statuses: '["list_id", "status_name"]'
    source_key = models.TextField(help_text="JSON-encoded source identifier")
    target_value = models.TextField(
        blank=True,
        help_text="Plane value (state group for statuses; priority string for priorities)",
    )
    approved = models.BooleanField(default=False, db_index=True)
    source_meta = models.JSONField(
        default=dict,
        help_text="Extra context for the reviewer (color, count, etc.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clickup_mapping_tables"
        unique_together = [("run", "kind", "source_key")]
        verbose_name = "Mapping Table Row"
        verbose_name_plural = "Mapping Table Rows"

    def __str__(self):
        return f"{self.kind} {self.source_key} → {self.target_value} (approved={self.approved})"


class EmailCoverage(models.Model):
    """Tracks ClickUp member email → Plane user mapping.

    signed_off must be True (per-row) before --apply writes any issue
    with that email as an assignee.  Null plane_user_id means the email
    was approved for bot-fallback.
    """

    run = models.ForeignKey(
        MigrationRun,
        on_delete=models.CASCADE,
        related_name="email_coverage",
    )
    clickup_email = models.EmailField(help_text="Email from ClickUp member")
    # Null = no matching Plane user; use the bot if signed_off is True
    plane_user_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Plane User.id (UUID string) or null for bot fallback",
    )
    signed_off = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Operator has signed off on this mapping (required before --apply)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clickup_email_coverage"
        unique_together = [("run", "clickup_email")]
        verbose_name = "Email Coverage Row"
        verbose_name_plural = "Email Coverage Rows"

    def __str__(self):
        return f"{self.clickup_email} → {self.plane_user_id or 'bot'} (signed_off={self.signed_off})"
