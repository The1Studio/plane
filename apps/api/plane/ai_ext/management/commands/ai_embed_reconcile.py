# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P4a — Reconciliation sweep management command.
# Bulk/cascade deletes fire NO post_save signal (Django limitation);
# this command finds orphaned AiEmbedding rows and purges them.
# Run periodically (e.g. weekly cron) or after bulk-delete operations.

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger("plane.ai_ext")


class Command(BaseCommand):
    help = "Purge orphaned ai_embeddings rows (no live entity in the DB)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts only; do not delete.",
        )
        parser.add_argument(
            "--workspace-slug",
            type=str,
            default=None,
            help="Limit reconciliation to a single workspace.",
        )

    def handle(self, *args, **options):
        from plane.db.models import Cycle, Issue, IssueComment, Module, Page, Project, Workspace
        from plane.ai_ext.models import AiEmbedding

        dry_run = options["dry_run"]
        workspace_slug = options["workspace_slug"]

        qs = AiEmbedding.objects.all()
        if workspace_slug:
            qs = qs.filter(workspace__slug=workspace_slug)

        # Build orphan checks per entity_type.
        entity_live_ids = {
            "issue": set(
                Issue.issue_objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
            ),
            "issue_comment": set(
                IssueComment.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
            ),
            "page": set(
                Page.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
            ),
            "cycle": set(
                Cycle.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
            ),
            "module": set(
                Module.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
            ),
            "project": set(Project.objects.values_list("id", flat=True)),
        }

        total_deleted = 0
        for entity_type, live_ids in entity_live_ids.items():
            orphans = qs.filter(entity_type=entity_type).exclude(entity_id__in=live_ids)
            count = orphans.count()
            if count:
                self.stdout.write(f"  [{entity_type}] {count} orphan chunks")
                if not dry_run:
                    orphans.delete()
                    total_deleted += count

        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(
            self.style.SUCCESS(f"[reconcile] {verb} {total_deleted} orphan embedding chunks.")
        )
