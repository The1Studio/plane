# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P3 — Management command to create/delete per-workspace digest PeriodicTasks.
# Uses django_celery_beat DatabaseScheduler (active in plane/celery.py via
# autodiscovery; no edit to celery.py required — docs/FORK.md touch-point 3).

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Create or delete per-workspace AI digest PeriodicTask rows "
        "(django_celery_beat DatabaseScheduler)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-slug",
            type=str,
            required=True,
            help="Workspace slug to schedule or unschedule.",
        )
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Remove the PeriodicTask for this workspace (opt-out).",
        )
        parser.add_argument(
            "--hour",
            type=int,
            default=9,
            help="Hour (0-23, workspace-local) to send digest (default: 9).",
        )
        parser.add_argument(
            "--timezone",
            type=str,
            default="UTC",
            help="Workspace timezone string (default: UTC).",
        )

    def handle(self, *args, **options):
        from django_celery_beat.models import CrontabSchedule, PeriodicTask  # type: ignore
        from plane.db.models import Workspace

        slug = options["workspace_slug"]
        try:
            workspace = Workspace.objects.get(slug=slug)
        except Workspace.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Workspace '{slug}' not found."))
            return

        task_name = f"ai_digest_{workspace.id}"

        if options["delete"]:
            deleted, _ = PeriodicTask.objects.filter(name=task_name).delete()
            if deleted:
                self.stdout.write(self.style.SUCCESS(f"Deleted PeriodicTask '{task_name}'"))
            else:
                self.stdout.write(f"No PeriodicTask found for '{task_name}'")
            return

        tz = options["timezone"]
        hour = options["hour"]

        # Night-before submission: schedule for ~11pm the previous day so
        # Batch completes before 9am target.  If the user wants a 9am digest,
        # we submit at 22:00 the night before (1h before midnight buffer).
        submit_hour = max(0, hour - 11) if hour >= 11 else 22

        crontab, _ = CrontabSchedule.objects.get_or_create(
            hour=str(submit_hour),
            minute="0",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=tz,
        )

        task, created = PeriodicTask.objects.update_or_create(
            name=task_name,
            defaults={
                "task": "plane.ai_ext.bgtasks.digest_task.submit_digest_batch",
                "crontab": crontab,
                "kwargs": f'{{"workspace_id": "{workspace.id}"}}',
                "enabled": True,
            },
        )

        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} PeriodicTask '{task_name}' (submit at {submit_hour:02d}:00 {tz})"
            )
        )


