# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork add-on — Neon CU-hr control.
#
# Upstream schedules `stack_email_notification` at `crontab(minute="*/5")` in
# plane/celery.py (docs/FORK.md touch-point 3 — zero edit). Its first statement
# is an unconditional read of EmailNotificationLog, so it touches the database
# every 5 minutes FOREVER, whether or not there is anything to send. The Neon
# compute suspends after 5 minutes of inactivity, so a database touch on that
# interval means the timer never expires and the compute is billed around the
# clock. This fork runs no mail server, so the job is dead weight.
#
# Why this is a DB row and not a celery.py edit: `DatabaseScheduler`
# (`beat_scheduler` in celery.py) builds its schedule from PeriodicTask rows and
# merges the static `app.conf.beat_schedule` into them at every boot via
# `update_from_dict`, which upserts each static entry by name. So popping the
# entry out of the in-memory dict is NOT enough — the persisted row outlives it,
# and `all_as_schedule` reads every enabled row regardless. The row is what
# fires.
#
# Why disabling the row is durable: `update_from_dict`'s upsert writes
# `_unpack_fields(...)` as its defaults, which carries the schedule columns and
# the option fields (queue, exchange, routing_key, priority, headers,
# expire_seconds) — `enabled` is not among them, and the static entry does not
# declare one. So a reboot re-asserts the schedule but never flips `enabled`
# back on. django-celery-beat also short-circuits a disabled entry in
# `is_due()`, so it stays out of the built schedule even if it lingers in it.
#
# Lives in ai_ext because this app already owns PeriodicTask management
# (ai_schedule_digests) and therefore the django_celery_beat dependency.

from django.core.management.base import BaseCommand


# The beat_schedule keys declared statically in plane/celery.py, mapped to the
# PeriodicTask `task` name that `update_from_dict` keys the DB row on. Edit
# celery.py to add one — it is touch-point 3, zero-edit.
# Default is the every-5-minutes email batch: its first statement is an
# unconditional read of EmailNotificationLog, so it touches the database every
# 5 minutes forever and never lets the Neon compute suspend.
JOBS = {
    "email": (
        "check-every-five-minutes-to-send-email-notifications",
        "plane.bgtasks.email_notification_task.stack_email_notification",
        "every 5 min — keeps the Neon compute awake 24/7",
    ),
    "instance-trace": (
        "run-every-6-hours-for-instance-trace",
        "plane.license.bgtasks.tracer.instance_traces",
        "every 6 h — emits ~9 count() queries covering every core table",
    ),
}


class Command(BaseCommand):
    help = (
        "Disable (or re-enable) a frequent static PeriodicTask so the Neon compute "
        "can suspend. Idempotent; safe to re-run on every deploy."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            choices=sorted(JOBS),
            default="email",
            help="Which scheduled job to act on (default: email).",
        )
        parser.add_argument(
            "--enable",
            action="store_true",
            help="Reverse it: re-enable the job instead of disabling it.",
        )

    def handle(self, *args, **options):
        from django_celery_beat.models import PeriodicTask  # type: ignore

        _, task_name, note = JOBS[options["job"]]
        enable = options["enable"]
        rows = PeriodicTask.objects.filter(name=task_name)

        if not rows.exists():
            # Not an error: the row is created by beat's first boot after a
            # fresh database, and by `update_from_dict` on the next one. Say so
            # rather than reporting a success that changed nothing.
            self.stdout.write(
                self.style.WARNING(
                    f"No PeriodicTask named '{task_name}' exists yet. Nothing to "
                    f"change. Re-run this after beat has booted once against this "
                    f"database and it will act on the row beat creates."
                )
            )
            return

        if enable:
            changed = rows.filter(enabled=False).update(enabled=True)
            self.stdout.write(
                self.style.SUCCESS(f"Re-enabled '{task_name}' ({changed} row(s)).")
            )
            return

        changed = rows.filter(enabled=True).update(enabled=False)
        if changed:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Disabled '{task_name}' ({changed} row(s); {note}). The compute "
                    f"can now suspend between the remaining jobs."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"'{task_name}' was already disabled. No change.")
            )
