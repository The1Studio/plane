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
# The other frequent STATIC entry is `instance_traces`, scheduled at
# `crontab(hour="*/6", minute=0)` in the same celery.py block. It reports
# instance telemetry upstream and emits ~9 `count()` queries covering every
# core table. Disabling it is the same problem and the same mechanism as the
# email job — a recurring database touch that never lets the compute's
# 5-minute idle timer expire — and the only difference between the two is
# cadence (every 6 hours against every 5 minutes), not how they are turned off.
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
# The lookup gotcha — the reason this command once shipped a false green.
# `update_from_dict` is handed the beat_schedule DICT, so its upsert is
# `PeriodicTask.objects.update_or_create(name=<dict KEY>, ...)`. Therefore
# `PeriodicTask.name` holds the beat_schedule KEY (e.g.
# "check-every-five-minutes-to-send-email-notifications") and the task path
# lives in the SEPARATE `task` column ("plane.bgtasks.email_notification_task.
# stack_email_notification"). Filtering by the task path — as this command
# first did — matches ZERO rows: it took its "no row yet" branch, printed
# success and exited 0 while every cron stayed enabled. Look the row up by the
# schedule key, and treat "no row" as the failure it is.
#
# Lives in ai_ext because this app already owns PeriodicTask management
# (ai_schedule_digests) and therefore the django_celery_beat dependency.

from django.core.management.base import BaseCommand, CommandError


# Each value is the tuple (schedule_key, task_path, note):
#   [0] schedule_key — the beat_schedule dict KEY in plane/celery.py. This is
#       the value `PeriodicTask.name` holds (`update_from_dict` upserts the row
#       keyed by it), so it is what the row is looked up BY.
#   [1] task_path — the `task` value of that same beat_schedule entry, i.e. the
#       value you find in the row's `task` column. Informational; it is NOT the
#       lookup key and filtering on it matches nothing.
#   [2] note — why this job keeps the Neon compute awake.
# Edit celery.py to add one — it is touch-point 3, zero-edit.
#
# The deploy step disables BOTH entries below, not just the default. Each is a
# recurring database touch that never lets the Neon compute's 5-minute idle
# timer expire: `email` fires every 5 minutes and reads EmailNotificationLog
# unconditionally (this fork runs no mail server, so it is dead weight), and
# `instance-trace` fires every 6 hours to report instance telemetry upstream,
# emitting ~9 `count()` queries covering every core table. Only the cadence
# differs; the mechanics are identical.
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
            help=(
                "Which frequent scheduled job to act on — 'email' (every 5 min) "
                "or 'instance-trace' (every 6 h). Both are disabled by the deploy "
                "step; default: email."
            ),
        )
        parser.add_argument(
            "--enable",
            action="store_true",
            help="Reverse it: re-enable the job instead of disabling it.",
        )

    def handle(self, *args, **options):
        from django_celery_beat.models import PeriodicTask  # type: ignore

        # `row_name` is the beat_schedule KEY — what `PeriodicTask.name` holds —
        # NOT the task path (element [1], which lives in the `task` column).
        row_name, _, note = JOBS[options["job"]]
        enable = options["enable"]
        rows = PeriodicTask.objects.filter(name=row_name)

        if not rows.exists():
            # HARD FAILURE, not a warning. A missing row means the disable did
            # not happen: beat creates the row on its first boot against this
            # database (`update_from_dict` upserts it from the celery.py
            # beat_schedule), so there is nothing to disable before then.
            # Raising exits non-zero — which is what lets deploy.sh step 7 take
            # its `else` branch and print the WARN line. The old silent success
            # here was the false green that let the crons stay enabled.
            raise CommandError(
                f"No PeriodicTask named '{row_name}' exists yet, so nothing was "
                f"disabled. That row is created by beat's first boot against this "
                f"database (celery.py's beat_schedule, upserted by "
                f"`update_from_dict`). Re-run this once beat has booted."
            )

        if enable:
            changed = rows.filter(enabled=False).update(enabled=True)
            self.stdout.write(
                self.style.SUCCESS(f"Re-enabled '{row_name}' ({changed} row(s)).")
            )
            return

        changed = rows.filter(enabled=True).update(enabled=False)
        if changed:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Disabled '{row_name}' ({changed} row(s); {note}). The compute "
                    f"can now suspend between the remaining jobs."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"'{row_name}' was already disabled. No change.")
            )
