# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — `migrate_clickup` management command.
#
# Usage:
#   python manage.py migrate_clickup --plan   [--space <id>] [--dry-run]
#   python manage.py migrate_clickup --apply  [--space <id>] [--dry-run]
#
# --plan:    Phase 3 — extract distinct values, run AI normalization,
#            write MappingTable (approved=false), emit review file. STOP.
# --apply:   Phases 4a/4b/5 — write entities to Plane. Refused unless
#            every MappingTable row is approved and EmailCoverage is signed.
# --dry-run: No .save() calls; emit would-create counts only.
# --space:   Scope to a single ClickUp Space (pilot run).
# --attachments: (--apply) Also migrate task attachments. Off by default because
#            ClickUp's list endpoint omits the attachments array (issue #6), so
#            enabling it costs one extra GET /task/{id} detail fetch per task.

import logging
import os
import time
from datetime import date

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Migrate ClickUp data into Plane (SP1 one-time ETL)"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--plan", action="store_true", help="Phase 3: extract + AI normalize + emit review file")
        mode.add_argument("--apply", action="store_true", help="Phase 4+: write entities (requires approved mappings)")

        parser.add_argument("--space", dest="space_ids", action="append", default=[], metavar="SPACE_ID",
                            help="Scope to one or more ClickUp Space IDs (repeatable)")
        parser.add_argument("--workspace", dest="workspace_slug", default=None, metavar="SLUG",
                            help="Target Plane Workspace slug. STRONGLY recommended whenever "
                                 "more than one workspace exists: the implicit fallback is "
                                 "Workspace.objects.first(), and Workspace.Meta.ordering is "
                                 "('-created_at',), so the target is the NEWEST workspace and "
                                 "silently retargets if anyone creates a newer one mid-migration.")
        parser.add_argument("--dry-run", action="store_true", help="No .save() calls; emit counts only")
        parser.add_argument("--since-days", type=int, default=None, metavar="N",
                            help="Only migrate tasks updated in the last N days. Filters on "
                                 "date_UPDATED (ClickUp date_updated_gt), not date_created — a "
                                 "task opened long ago but touched recently IS in scope. "
                                 "Out-of-window parents and dependency targets of in-window "
                                 "tasks are pulled in too (ancestor backfill), so "
                                 "hierarchy/relations stay intact; this applies to BOTH --plan "
                                 "and --apply (before 2026-07-28 --apply skipped the backfill "
                                 "and silently orphaned such subtasks). Omit for full history.")
        parser.add_argument("--auto-map", action="store_true",
                            help="(--plan) Skip Anthropic; map statuses by keyword "
                                 "heuristic, write MappingTable rows approved=True, and "
                                 "auto-sign EmailCoverage. Lets --apply proceed with NO "
                                 "ANTHROPIC_API_KEY. Unknown statuses default to 'backlog' "
                                 "(logged).")
        parser.add_argument("--attachments", action="store_true",
                            help="(--apply) Migrate task attachments. Off by default "
                                 "because ClickUp's list endpoint omits the attachments "
                                 "array (issue #6), so each task needs an extra single-task "
                                 "detail fetch (GET /task/{id}) — ~1 additional API call per "
                                 "task. Enable for a completeness run; leave off for a fast "
                                 "metadata-only migration. ClickUp attachment URLs are "
                                 "pre-signed (*.clickup-attachments.com) and REJECT the auth "
                                 "header (verified: with-auth 401, without 206), so downloads "
                                 "default to sending NO auth; set CLICKUP_ATTACHMENT_USE_AUTH=1 "
                                 "to force the token header on for a workspace that needs it.")
        parser.add_argument("--snapshot", dest="snapshot_path", default=None, metavar="PATH",
                            help="Portable JSONL raw-extract snapshot. Decouples extract "
                                 "from load so the same task set can be replayed into "
                                 "another instance (staging -> prod) without re-crawling. "
                                 "If PATH does not exist, tasks are crawled per --since-days "
                                 "and written there. If it DOES exist, tasks are read from it "
                                 "and ClickUp is not paged for tasks at all (unless "
                                 "--snapshot-refresh). Tasks only: comments and container "
                                 "structure are still fetched live.")
        parser.add_argument("--snapshot-refresh", action="store_true",
                            help="(with --snapshot, on an existing file) Pull only tasks "
                                 "updated since the snapshot's watermark, merge them in "
                                 "(delta wins per task id), rewrite the snapshot, and use the "
                                 "merged set. This is the 'only fetch what changed, then "
                                 "import everything' path. Deletions are NOT detected.")
        parser.add_argument("--run-id", type=int, default=None,
                            help="Resume an existing MigrationRun by ID (else creates a new one)")
        parser.add_argument("--review-dir", default=".", metavar="DIR",
                            help="Directory to write the human-review file (--plan only)")

    def handle(self, *args, **options):
        # ── environment ───────────────────────────────────────────────
        token = os.environ.get("CLICKUP_TOKEN") or ""
        team_id = os.environ.get("CLICKUP_TEAM_ID") or ""
        if not token or not team_id:
            raise CommandError(
                "CLICKUP_TOKEN and CLICKUP_TEAM_ID environment variables are required."
            )

        bot_email = os.environ.get("CLICKUP_BOT_EMAIL", "migration-bot@clickup.local")
        dry_run: bool = options["dry_run"]
        space_ids: list[str] = options["space_ids"]
        run_id: int | None = options["run_id"]
        review_dir: str = options["review_dir"]
        since_days: int | None = options["since_days"]

        # "Last N days" window → ClickUp date_updated_gt (Unix ms).
        # None means full history.
        date_updated_gt: int | None = None
        if since_days is not None:
            if since_days <= 0:
                raise CommandError("--since-days must be a positive integer.")
            date_updated_gt = int((time.time() - since_days * 86400) * 1000)
            self.stdout.write(
                f"Window: tasks updated in the last {since_days} day(s) "
                f"(date_updated_gt={date_updated_gt})"
            )

        from plane.clickup_migrate.client import ClickUpClient
        from plane.clickup_migrate.models import MigrationRun
        from plane.db.models import User, Workspace

        client = ClickUpClient(token=token, team_id=team_id)

        # ── workspace + bot user ──────────────────────────────────────
        workspace_slug: str | None = options["workspace_slug"]
        if workspace_slug:
            try:
                workspace = Workspace.objects.get(slug=workspace_slug)
            except Workspace.DoesNotExist:
                known = ", ".join(
                    Workspace.objects.filter(slug__isnull=False).values_list("slug", flat=True)
                ) or "(none)"
                raise CommandError(
                    f"Workspace '{workspace_slug}' not found. Known slugs: {known}"
                )
        else:
            candidates = list(Workspace.objects.filter(slug__isnull=False)[:2])
            if not candidates:
                raise CommandError("No Workspace found in the database. Did SP0 run?")
            workspace = candidates[0]
            if len(candidates) > 1:
                # Ordering is ('-created_at',), so this silently picks the NEWEST
                # workspace — and retargets if a newer one appears mid-migration.
                # Refuse to guess when the choice is ambiguous.
                known = ", ".join(
                    Workspace.objects.filter(slug__isnull=False).values_list("slug", flat=True)
                )
                raise CommandError(
                    "Multiple workspaces exist and --workspace was not given; refusing to "
                    f"guess a migration target. Known slugs: {known}. "
                    f"Re-run with --workspace <slug> (implicit pick would have been "
                    f"'{workspace.slug}')."
                )
        self.stdout.write(f"Target workspace: {workspace.slug}")

        try:
            bot_user = User.objects.get(email__iexact=bot_email)
        except User.DoesNotExist:
            raise CommandError(
                f"Bot user '{bot_email}' not found. "
                "Create a 'ClickUp Migration' user in Plane before running the migration."
            )

        # ── MigrationRun ──────────────────────────────────────────────
        # H1: gate ALL DB writes on dry_run — dry-run must emit zero rows.
        if run_id:
            try:
                run = MigrationRun.objects.get(pk=run_id)
                self.stdout.write(f"Resuming MigrationRun #{run.pk}")
            except MigrationRun.DoesNotExist:
                raise CommandError(f"MigrationRun #{run_id} not found.")
        elif dry_run:
            # H1: No MigrationRun row in dry-run — use a sentinel.
            run = None
            self.stdout.write("[dry-run] No MigrationRun created")
        else:
            run = MigrationRun.objects.create(
                space_ids=space_ids,
                dry_run=dry_run,
                status="pending",
            )
            self.stdout.write(f"Created MigrationRun #{run.pk}")

        # ── snapshot (extract/load decoupling) ────────────────────────
        # Resolved BEFORE dispatch so both --plan and --apply see the same
        # task set. snapshot_by_list is None when tasks should be crawled live.
        snapshot_path: str | None = options["snapshot_path"]
        snapshot_refresh: bool = options["snapshot_refresh"]
        if snapshot_refresh and not snapshot_path:
            raise CommandError("--snapshot-refresh requires --snapshot PATH.")

        snapshot_by_list = self._load_snapshot(
            client, space_ids, snapshot_path, snapshot_refresh, since_days,
        )

        # ── dispatch ──────────────────────────────────────────────────
        if options["plan"]:
            self._run_plan(run, client, workspace, bot_user, space_ids, dry_run, review_dir,
                           date_updated_gt, auto_map=options["auto_map"],
                           snapshot_path=snapshot_path, snapshot_by_list=snapshot_by_list,
                           since_days=since_days)
        else:
            self._run_apply(run, client, workspace, bot_user, space_ids, dry_run, date_updated_gt,
                            migrate_attachments=options["attachments"],
                            snapshot_path=snapshot_path, snapshot_by_list=snapshot_by_list,
                            since_days=since_days)

    # ─────────────────────────────────────────────────────────────────
    # Snapshot plumbing
    # ─────────────────────────────────────────────────────────────────

    def _crawl_all_tasks(self, client, space_ids, date_updated_gt):
        """Flat task crawl across the selected spaces (both archived states)."""
        all_spaces = client.get_spaces()
        spaces = [s for s in all_spaces if str(s["id"]) in space_ids] if space_ids else all_spaces

        tasks: list[dict] = []
        for space in spaces:
            sid = space["id"]
            list_ids = [lst["id"] for lst in client.get_folderless_lists(sid)]
            for folder in client.get_folders(sid):
                list_ids.extend(lst["id"] for lst in client.get_lists_in_folder(folder["id"]))
            for lid in list_ids:
                for archived in (False, True):
                    for page, _ in client.iter_tasks(
                        lid, archived=archived, date_updated_gt=date_updated_gt
                    ):
                        tasks.extend(page)
        return self._dedupe_tasks(tasks)

    def _load_snapshot(self, client, space_ids, snapshot_path, snapshot_refresh, since_days):
        """Resolve the task source. Returns tasks-by-list, or None to crawl live.

        None is returned when there is no snapshot path, or the file does not
        exist yet — in that case the normal crawl runs and the snapshot is
        written afterwards from the tasks it collected (see _write_snapshot).
        """
        from plane.clickup_migrate import snapshot as snap

        if not snapshot_path:
            return None

        if not os.path.exists(snapshot_path):
            if snapshot_refresh:
                raise CommandError(
                    f"--snapshot-refresh given but {snapshot_path} does not exist. "
                    "Run once without --snapshot-refresh to seed the snapshot first."
                )
            self.stdout.write(
                f"Snapshot {snapshot_path} not found — crawling live and writing it afterwards."
            )
            return None

        tasks_by_id, manifest = snap.read(snapshot_path)
        self.stdout.write(
            f"Snapshot loaded: {snapshot_path} "
            f"({len(tasks_by_id)} tasks, watermark={manifest.get('watermark')})"
        )

        if snapshot_refresh:
            watermark = manifest.get("watermark")
            if watermark is None:
                raise CommandError(
                    f"{snapshot_path} has no watermark — cannot compute a delta. "
                    "Re-seed the snapshot with a full run."
                )
            self.stdout.write(f"Delta: pulling tasks updated since watermark {watermark} …")
            delta = self._crawl_all_tasks(client, space_ids, watermark)
            merged, updated, added = snap.merge(tasks_by_id, delta)
            self.stdout.write(
                f"Delta: {len(delta)} task(s) fetched — {updated} updated, {added} new; "
                f"snapshot now {len(merged)} task(s)"
            )
            snap.write(
                snapshot_path, merged.values(),
                space_ids=space_ids, since_days=since_days,
            )
            tasks_by_id = merged

        by_list = snap.group_by_list(tasks_by_id.values())
        dropped = len(tasks_by_id) - sum(len(v) for v in by_list.values())
        if dropped:
            self.stderr.write(
                f"WARNING: {dropped} snapshot task(s) have no resolvable list id "
                "and cannot be placed in a Project — skipped."
            )
        return by_list

    def _write_snapshot(self, snapshot_path, tasks, space_ids, since_days):
        """Persist a freshly-crawled task set. No-op without --snapshot."""
        if not snapshot_path:
            return
        from plane.clickup_migrate import snapshot as snap

        manifest = snap.write(
            snapshot_path, tasks, space_ids=space_ids, since_days=since_days,
        )
        self.stdout.write(
            f"Snapshot written: {snapshot_path} "
            f"({manifest['task_count']} tasks, watermark={manifest['watermark']})"
        )

    # ─────────────────────────────────────────────────────────────────
    # Phase 3 — --plan
    # ─────────────────────────────────────────────────────────────────

    def _run_plan(self, run, client, workspace, bot_user, space_ids, dry_run, review_dir,
                  date_updated_gt=None, auto_map=False,
                  snapshot_path=None, snapshot_by_list=None, since_days=None):
        import os

        from plane.clickup_migrate.models import EmailCoverage, MappingTable
        from plane.clickup_migrate.normalize import (
            collect_distinct_statuses,
            collect_distinct_custom_field_defs,
            run_anthropic_batch,
            build_mapping_rows,
            emit_review_file,
            _make_status_batch_requests,
            _make_field_batch_requests,
        )

        if run is not None:
            run.status = "normalizing"
            run.save(update_fields=["status"])

        self.stdout.write("Phase 3: extracting distinct values …")

        # ── collect spaces ────────────────────────────────────────────
        all_spaces = client.get_spaces()
        if space_ids:
            spaces = [s for s in all_spaces if str(s["id"]) in space_ids]
        else:
            spaces = all_spaces
        self.stdout.write(f"Processing {len(spaces)} space(s)")

        # ── collect members for email coverage ────────────────────────
        members = client.get_team_members()
        self.stdout.write(f"Found {len(members)} workspace members")

        for member in members:
            email = (member.get("user") or {}).get("email") or ""
            if not email:
                continue
            from plane.db.models import User
            try:
                user = User.objects.get(email__iexact=email)
                plane_uid = str(user.id)
            except User.DoesNotExist:
                plane_uid = None

            # H1: skip EmailCoverage writes entirely in dry-run.
            # auto-map signs coverage so --apply's gate passes with no manual step.
            if not dry_run:
                EmailCoverage.objects.get_or_create(
                    run=run,
                    clickup_email=email,
                    defaults={"plane_user_id": plane_uid, "signed_off": bool(auto_map)},
                )

        # ── collect tasks + field defs ─────────────────────────────────
        all_tasks: list[dict] = []
        field_defs_by_list: dict[str, list] = {}

        for space in spaces:
            sid = space["id"]
            # Folderless lists.
            for lst in client.get_folderless_lists(sid):
                lid = lst["id"]
                field_defs_by_list[lid] = client.get_field_defs(lid)
                if snapshot_by_list is not None:
                    all_tasks.extend(snapshot_by_list.get(lid, []))
                    continue
                for tasks_page, _ in client.iter_tasks(lid, archived=False, date_updated_gt=date_updated_gt):
                    all_tasks.extend(tasks_page)
                for tasks_page, _ in client.iter_tasks(lid, archived=True, date_updated_gt=date_updated_gt):
                    all_tasks.extend(tasks_page)
            # Folders + their lists.
            for folder in client.get_folders(sid):
                for lst in client.get_lists_in_folder(folder["id"]):
                    lid = lst["id"]
                    field_defs_by_list[lid] = client.get_field_defs(lid)
                    if snapshot_by_list is not None:
                        all_tasks.extend(snapshot_by_list.get(lid, []))
                        continue
                    for tasks_page, _ in client.iter_tasks(lid, archived=False, date_updated_gt=date_updated_gt):
                        all_tasks.extend(tasks_page)
                    for tasks_page, _ in client.iter_tasks(lid, archived=True, date_updated_gt=date_updated_gt):
                        all_tasks.extend(tasks_page)

        # Deduplicate tasks by id.
        all_tasks = self._dedupe_tasks(all_tasks)
        in_window = len(all_tasks)
        self.stdout.write(f"Collected {in_window} in-window task(s)")

        # Ancestor backfill: when a window is set, pull out-of-window
        # parents + dependency targets so hierarchy/relations stay intact.
        # Skipped when replaying a snapshot: the snapshot already contains
        # whatever ancestors were resolved when it was seeded, and re-walking
        # them would issue exactly the per-task fetches the snapshot avoids.
        ancestors = 0
        if date_updated_gt is not None and snapshot_by_list is None:
            all_tasks, ancestors = self._backfill_ancestors(client, all_tasks)
            if ancestors:
                self.stdout.write(f"Backfilled {ancestors} out-of-window ancestor/relation task(s)")

        # Persist the freshly-crawled set (no-op without --snapshot, and skipped
        # when we replayed one — _load_snapshot already rewrote it on refresh).
        if snapshot_by_list is None:
            self._write_snapshot(snapshot_path, all_tasks, space_ids, since_days)

        distinct_statuses = collect_distinct_statuses(all_tasks)
        distinct_fields = collect_distinct_custom_field_defs(field_defs_by_list)
        self.stdout.write(f"Distinct statuses: {len(distinct_statuses)}, custom fields: {len(distinct_fields)}")

        # ── dry-run: counts only, no AI, no writes ────────────────────
        # The counts above are the whole point of a dry-run; the Anthropic
        # normalization below is only needed to build the approval tables
        # for a real --apply, so a dry-run needs no ANTHROPIC_API_KEY.
        if dry_run:
            self.stdout.write("\n=== Plan dry-run summary ===")
            self.stdout.write(f"  spaces:            {len(spaces)}")
            self.stdout.write(f"  members:           {len(members)}")
            self.stdout.write(f"  in-window tasks:   {in_window}")
            self.stdout.write(f"  ancestor backfill: {ancestors}")
            self.stdout.write(f"  total tasks:       {len(all_tasks)}")
            self.stdout.write(f"  distinct statuses: {len(distinct_statuses)}")
            self.stdout.write(f"  custom fields:     {len(distinct_fields)}")
            self.stdout.write("[DRY RUN — no AI call, no data written]")
            return

        # ── auto-map: heuristic status mapping, no Anthropic ──────────
        if auto_map:
            status_results = {}
            unknown = []
            for i, s in enumerate(distinct_statuses):
                grp = self._heuristic_status_group(s["status_name"])
                status_results[f"status-{i}"] = grp or "backlog"
                if grp is None:
                    unknown.append(s["status_name"])
            mapping_rows, rejected_rows = build_mapping_rows(
                run, distinct_statuses, status_results, distinct_fields, {}
            )
            all_rows = mapping_rows + rejected_rows
            for r in all_rows:
                r.approved = True
            MappingTable.objects.bulk_create(all_rows, ignore_conflicts=True)
            self.stdout.write(
                f"[auto-map] wrote {len(all_rows)} approved MappingTable row(s); "
                f"{len(unknown)} status(es) defaulted to 'backlog'"
            )
            if unknown:
                sample = ", ".join(sorted(set(unknown))[:15])
                self.stdout.write(f"[auto-map] defaulted statuses (sample): {sample}")
            review_path = os.path.join(review_dir, f"clickup-migration-review-{date.today()}.md")
            emit_review_file(review_path, distinct_statuses, mapping_rows, rejected_rows, distinct_fields)
            self.stdout.write(f"Review file: {review_path}")
            if run is not None:
                run.status = "pending"
                run.save(update_fields=["status"])
            self.stdout.write("[auto-map] Mappings approved. Ready for --apply.")
            return

        # ── Anthropic Batches ─────────────────────────────────────────
        import anthropic as ant
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or ""
        if not anthropic_key:
            raise CommandError("ANTHROPIC_API_KEY environment variable required for --plan (non-dry-run).")

        ai_client = ant.Anthropic(api_key=anthropic_key)

        status_batch_reqs = _make_status_batch_requests(distinct_statuses)
        field_batch_reqs = _make_field_batch_requests(distinct_fields)

        status_results: dict = {}
        if status_batch_reqs:
            self.stdout.write(f"Submitting status batch ({len(status_batch_reqs)} requests) …")
            status_results = run_anthropic_batch(ai_client, status_batch_reqs)

        field_results: dict = {}
        if field_batch_reqs:
            self.stdout.write(f"Submitting field batch ({len(field_batch_reqs)} requests) …")
            field_results = run_anthropic_batch(ai_client, field_batch_reqs)

        # ── build and save mapping rows ───────────────────────────────
        mapping_rows, rejected_rows = build_mapping_rows(
            run, distinct_statuses, status_results, distinct_fields, field_results
        )

        all_rows = mapping_rows + rejected_rows
        if not dry_run:
            MappingTable.objects.bulk_create(all_rows, ignore_conflicts=True)
            self.stdout.write(f"Saved {len(all_rows)} MappingTable rows ({len(rejected_rows)} rejected)")

        # ── emit review file ──────────────────────────────────────────
        review_path = os.path.join(review_dir, f"clickup-migration-review-{date.today()}.md")
        emit_review_file(review_path, distinct_statuses, mapping_rows, rejected_rows, distinct_fields)
        self.stdout.write(f"Review file: {review_path}")

        if rejected_rows:
            self.stderr.write(
                f"WARNING: {len(rejected_rows)} status(es) had invalid AI output. "
                "Manually set target_value and approved=true before running --apply."
            )

        run.status = "pending"  # wait for human approval
        if not dry_run:
            run.save(update_fields=["status"])

        self.stdout.write(
            "Phase 3 complete. Review the mapping file, approve all rows in the DB, "
            "then run --apply."
        )

    # ─────────────────────────────────────────────────────────────────
    # Shared extraction helpers
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _dedupe_tasks(tasks):
        """De-duplicate a task list by id, preserving first-seen order."""
        seen: set[str] = set()
        out: list[dict] = []
        for t in tasks:
            tid = str(t.get("id", ""))
            if tid and tid not in seen:
                seen.add(tid)
                out.append(t)
        return out

    @staticmethod
    def _heuristic_status_group(status_name):
        """Map a ClickUp status name → Plane state group by keyword.

        Returns backlog/unstarted/started/completed/cancelled, or None when
        no keyword matches (caller defaults to 'backlog'). Order matters:
        cancelled/completed are checked before started/unstarted so that
        e.g. 'review complete' resolves to completed, not started.
        """
        n = (status_name or "").strip().lower()
        if not n:
            return None
        # Order matters. cancelled/completed first; then unstarted BEFORE
        # started so "not started"/"unstarted" don't match the "started"
        # substring; backlog last as the catch-all for hold/pending states.
        groups = [
            ("cancelled", ("cancel", "won't", "wont", "reject", "duplicate",
                           "invalid", "dropped", "abandon", "archive")),
            ("completed", ("complete", "closed", "done", "resolved", "finished",
                           "live", "published", "released", "shipped", "merged",
                           "approved")),
            ("unstarted", ("to do", "todo", "to-do", "not started", "unstarted",
                           "open", "new", "ready", "planned", "queue")),
            ("started", ("progress", "doing", "wip", "develop", "dev", "coding",
                         "code", "review", "qa", "test", "design", "art", "build",
                         "fix", "implement", "feedback", "polish", "working",
                         "started", "ongoing", "active")),
            ("backlog", ("backlog", "icebox", "hold", "paused", "someday", "idea",
                         "pending", "waiting", "block")),
        ]
        for group, keywords in groups:
            if any(kw in n for kw in keywords):
                return group
        return None

    @staticmethod
    def _referenced_task_ids(task) -> set[str]:
        """Parent + dependency + linked task ids referenced by a task."""
        ids: set[str] = set()
        for key in ("parent", "top_level_parent"):
            val = task.get(key)
            if val:
                ids.add(str(val))
        for dep in (task.get("dependencies") or []):
            tid = dep.get("task_id")
            if tid:
                ids.add(str(tid))
        for ln in (task.get("linked_tasks") or []):
            tid = ln.get("task_id") or ln.get("link_id")
            if tid:
                ids.add(str(tid))
        return ids

    def _backfill_ancestors(self, client, tasks, max_rounds: int = 10):
        """Fetch out-of-window parents/dependency targets to closure.

        Given an in-window task set, repeatedly fetch any referenced
        parent / dependency / linked task not already present, until no
        new ids appear (transitive closure) or ``max_rounds`` is reached.
        A deleted/inaccessible reference (404 → None) is recorded so it is
        not refetched; pass-2 later flags it as an orphan.

        Returns ``(complete_task_list, backfilled_count)``.
        """
        by_id: dict[str, dict | None] = {
            str(t.get("id", "")): t for t in tasks if t.get("id")
        }

        frontier: set[str] = set()
        for t in tasks:
            frontier |= self._referenced_task_ids(t)
        frontier -= set(by_id)

        backfilled = 0
        rounds = 0
        while frontier and rounds < max_rounds:
            rounds += 1
            next_frontier: set[str] = set()
            for tid in sorted(frontier):
                if tid in by_id:
                    continue
                fetched = client.get_task(tid)
                by_id[tid] = fetched  # None marks deleted/visited
                if fetched is None:
                    continue
                backfilled += 1
                next_frontier |= self._referenced_task_ids(fetched)
            frontier = {i for i in next_frontier if i not in by_id}

        complete = [t for t in by_id.values() if t is not None]
        return complete, backfilled

    @staticmethod
    def _resolve_attachments(task, task_id, client, migrate_attachments, counts):
        """Return the attachment list for a task, fetching detail when needed.

        Issue #6: the extractor pulls tasks via ClickUp's LIST endpoint
        (``GET /list/{id}/task``), whose task objects DO NOT carry the
        ``attachments`` array. The single-task detail endpoint
        (``GET /task/{id}``) does. So:

          * ``migrate_attachments`` off → return [] (no attachments, no cost).
          * on, list-view task already carries ``attachments`` → use it as-is.
          * on, ``attachments`` absent → one detail fetch, count it, use the
            detail's attachments (``[]`` if the task genuinely has none, or
            the detail was a 404/None).

        Pure and side-effect-free apart from bumping ``counts`` — unit-tested
        without a DB or live ClickUp connection.
        """
        if not migrate_attachments:
            return []
        attachments = task.get("attachments")
        if attachments is None:
            detail = client.get_task(task_id)
            counts["attachment_detail_fetch"] += 1
            attachments = (detail or {}).get("attachments") or []
        return attachments

    # ─────────────────────────────────────────────────────────────────
    # Phases 4a / 4b / 5 — --apply
    # ─────────────────────────────────────────────────────────────────

    def _run_apply(self, run, client, workspace, bot_user, space_ids, dry_run, date_updated_gt=None,
                   migrate_attachments=False,
                   snapshot_path=None, snapshot_by_list=None, since_days=None):
        from plane.clickup_migrate.writers import (
            UserCache,
            MappingCache,
            check_apply_gate,
            write_project,
            write_state,
            write_label,
            write_module,
            write_subtask_parent,
            write_issue_relation,
            write_workload_estimate,
            _parse_ms_estimate,
        )
        from plane.workload.rollup import parent_issue_ids
        from plane.workload.aggregation import MAX_HOURS

        # ── gate check ────────────────────────────────────────────────
        blockers = check_apply_gate(run)
        if blockers:
            for b in blockers:
                self.stderr.write(f"BLOCKED: {b}")
            raise CommandError(
                "--apply refused: resolve all blockers above first."
            )

        run.status = "writing"
        if not dry_run:
            run.save(update_fields=["status"])

        user_cache = UserCache(bot_user)
        mapping_cache = MappingCache(run)

        # Attachment download auth: ClickUp attachment URLs are pre-signed
        # (*.clickup-attachments.com) and REJECT the Authorization header —
        # verified against this workspace: with-auth → 401, without → 206.
        # So default to NO auth header; set CLICKUP_ATTACHMENT_USE_AUTH=1 to
        # force it on for a workspace whose URLs require the token.
        use_auth: bool = os.environ.get("CLICKUP_ATTACHMENT_USE_AUTH", "").strip().lower() in ("1", "true", "yes")
        if migrate_attachments:
            self.stdout.write(
                f"Attachments: ENABLED (per-task detail fetch; "
                f"download {'WITH' if use_auth else 'WITHOUT'} auth header)"
            )

        # ── pass-0: ancestor backfill (windowed runs) ─────────────────
        # --plan has always closed over out-of-window parents / dependency
        # targets so hierarchy survives a --since-days window; --apply never
        # did, despite --since-days' help text promising exactly that. The
        # result was silent orphaning: on the 2026-07-28 staging run, 296
        # subtasks whose parent sat outside the 90-day window were logged
        # "Orphan subtask" and landed at top level instead of nested.
        #
        # Rather than re-plumb the streaming write path, pre-crawl the window,
        # close over its ancestors, and hand the result to the SAME
        # tasks-by-list channel a snapshot replay uses. Memory is the same
        # shape --plan has always held (~10.6k task dicts).
        #
        # Windowed runs only: with no window every task is already in scope,
        # so streaming is kept there to avoid loading full history at once.
        if snapshot_by_list is None and date_updated_gt is not None:
            from plane.clickup_migrate import snapshot as snap

            self.stdout.write("Pass-0: pre-crawling window to close over ancestors …")
            windowed = self._crawl_all_tasks(client, space_ids, date_updated_gt)
            complete, ancestors = self._backfill_ancestors(client, windowed)
            self.stdout.write(
                f"Pass-0: {len(windowed)} in-window task(s) "
                f"+ {ancestors} out-of-window ancestor/relation task(s) "
                f"= {len(complete)} total"
            )
            snapshot_by_list = snap.group_by_list(complete)
            self._write_snapshot(snapshot_path, complete, space_ids, since_days)

        all_spaces = client.get_spaces()
        if space_ids:
            spaces = [s for s in all_spaces if str(s["id"]) in space_ids]
        else:
            spaces = all_spaces

        # ── statistics counters ───────────────────────────────────────
        counts = {
            "project": 0, "state": 0, "label": 0, "module": 0,
            "issue": 0, "assignee": 0, "label_link": 0,
            "module_issue": 0, "subscriber": 0, "comment": 0,
            "attachment": 0, "attachment_detail_fetch": 0, "relation": 0, "parent_link": 0,
            "estimate": 0, "estimate_parent_skip": 0,
        }
        total_hours = 0.0

        # Map ClickUp task_id → Plane Issue (for pass-2 + junctions).
        task_to_issue: dict[str, object] = {}
        # Map ClickUp task_id → parent_task_id.
        subtask_parents: dict[str, str] = {}
        # Collect all raw tasks for pass-2 relations.
        all_tasks_raw: dict[str, dict] = {}

        # ── per-space traversal ───────────────────────────────────────
        for space in spaces:
            sid = space["id"]
            space_tags = client.get_space_tags(sid)

            # ── folderless lists → Projects ───────────────────────────
            for lst in client.get_folderless_lists(sid):
                lid = lst["id"]
                field_defs_raw = client.get_field_defs(lid)
                field_defs = {f["id"]: f for f in field_defs_raw}

                project = write_project(run, workspace, lst, user_cache, dry_run)
                counts["project"] += 1

                # States: one per distinct status in this list.
                list_statuses = lst.get("statuses") or []
                default_set = False
                state_map: dict[str, object] = {}
                for s_obj in list_statuses:
                    group = mapping_cache.status_group(lid, s_obj.get("status", ""))
                    is_default = not default_set
                    state = write_state(run, project, workspace, lid, s_obj, group, is_default, user_cache, dry_run)
                    if state:
                        default_set = True
                        state_map[s_obj.get("status", "")] = state
                    counts["state"] += 1

                # Ensure at least one default state.
                if project and not default_set and not dry_run:
                    from plane.db.models import State
                    # C1: BaseModel.save() clears created_by via crum in management
                    # commands. Use the post-save .save(disable_auto_set_user=True) pattern.
                    # Idempotent: update_or_create so a re-run heals instead of
                    # colliding on state_unique_name_project_when_deleted_at_null.
                    fallback_state, _ = State.all_state_objects.update_or_create(
                        project=project,
                        name="Backlog",
                        defaults={
                            "workspace": workspace,
                            "color": "#60646C",
                            "group": "backlog",
                            "default": True,
                        },
                    )
                    fallback_state.save(
                        created_by_id=bot_user.id,
                        disable_auto_set_user=True,
                    )

                # Labels from tags.
                label_map: dict[str, object] = {}
                for tag in space_tags:
                    label = write_label(run, workspace, project, tag, user_cache, dry_run)
                    if label:
                        label_map[tag.get("name", "")] = label
                    counts["label"] += 1

                # Tasks.
                self._apply_list_tasks(
                    run, client, lid, project, workspace, state_map, label_map,
                    field_defs, mapping_cache, user_cache, bot_user,
                    use_auth, dry_run, counts, task_to_issue, subtask_parents, all_tasks_raw,
                    date_updated_gt=date_updated_gt,
                    migrate_attachments=migrate_attachments,
                    snapshot_by_list=snapshot_by_list,
                )

            # ── folders → Project + Modules ───────────────────────────
            for folder in client.get_folders(sid):
                project = write_project(run, workspace, folder, user_cache, dry_run)
                counts["project"] += 1

                # Tags for labels.
                label_map: dict[str, object] = {}
                for tag in space_tags:
                    label = write_label(run, workspace, project, tag, user_cache, dry_run)
                    if label:
                        label_map[tag.get("name", "")] = label
                    counts["label"] += 1

                for lst in client.get_lists_in_folder(folder["id"]):
                    lid = lst["id"]
                    field_defs_raw = client.get_field_defs(lid)
                    field_defs = {f["id"]: f for f in field_defs_raw}

                    # Lists inside folders → Modules.
                    module = write_module(run, project, workspace, lst, user_cache, dry_run)
                    counts["module"] += 1

                    # States.
                    list_statuses = lst.get("statuses") or []
                    default_set = False
                    state_map: dict[str, object] = {}
                    for s_obj in list_statuses:
                        group = mapping_cache.status_group(lid, s_obj.get("status", ""))
                        is_default = not default_set
                        state = write_state(run, project, workspace, lid, s_obj, group, is_default, user_cache, dry_run)
                        if state:
                            default_set = True
                            state_map[s_obj.get("status", "")] = state
                        counts["state"] += 1

                    # Tasks.
                    self._apply_list_tasks(
                        run, client, lid, project, workspace, state_map, label_map,
                        field_defs, mapping_cache, user_cache, bot_user,
                        use_auth, dry_run, counts, task_to_issue, subtask_parents, all_tasks_raw,
                        module=module,
                        date_updated_gt=date_updated_gt,
                        migrate_attachments=migrate_attachments,
                        snapshot_by_list=snapshot_by_list,
                    )

        # ── pass-2: subtask parents ───────────────────────────────────
        self.stdout.write(f"Pass-2: linking {len(subtask_parents)} subtask parent(s) …")
        for child_id, parent_id in subtask_parents.items():
            ok = write_subtask_parent(run, child_id, parent_id, dry_run)
            if ok:
                counts["parent_link"] += 1

        # ── pass-2: issue relations ───────────────────────────────────
        # C3 fix: write_issue_relation resolves project from the DB (Issue
        # lookup via ledger plane_id) — the in-memory task_to_issue map is
        # empty on a resumed run and MUST NOT be used for project resolution.
        for task_id, task in all_tasks_raw.items():
            deps = task.get("dependencies") or []
            for dep in deps:
                dep_task_id = str(dep.get("task_id", ""))
                dep_type = dep.get("type", "waiting_on")
                if dep_task_id:
                    write_issue_relation(
                        run, dep_type, task_id, dep_task_id,
                        workspace, bot_user, dry_run,
                    )
                    counts["relation"] += 1

        # ── pass-3: workload estimates (leaf-only) ────────────────────
        # Blocked-by pass-2 parent-linking above: leaf-ness is only correct
        # once Issue.parent has been committed. Batch-compute the parent
        # set once (REUSE workload/rollup.py::parent_issue_ids) instead of
        # querying is_parent() per issue.
        #
        # C3-style caveat (mirrors the pass-2 relations loop above): on a
        # resumed run, `task_to_issue` may be a partial in-memory map (only
        # tasks processed in THIS invocation are present). Tasks migrated by
        # an earlier invocation of the same run are skipped here rather than
        # re-resolved via the ledger — acceptable for the common single-run
        # path; a full resumed-run fix would need a ledger-backed
        # task_id -> Issue lookup, out of scope for this pass.
        self.stdout.write(f"Pass-3: writing workload estimates for {len(all_tasks_raw)} task(s) …")
        migrated_issues = list(task_to_issue.values())
        parent_ids = set(parent_issue_ids([iss.id for iss in migrated_issues])) if migrated_issues else set()

        for task_id, task in all_tasks_raw.items():
            issue = task_to_issue.get(task_id)
            if issue is None:
                continue
            raw_ms = task.get("time_estimate")
            is_leaf = issue.id not in parent_ids
            token = write_workload_estimate(run, issue, task_id, raw_ms, is_leaf, user_cache, dry_run)
            if token in ("created", "updated", "clamped"):
                counts["estimate"] += 1
                ms = _parse_ms_estimate(raw_ms)
                if ms and is_leaf:
                    total_hours += min(round(ms / 3_600_000, 2), MAX_HOURS)
            elif token == "skipped-parent":
                counts["estimate_parent_skip"] += 1

        run.status = "done" if not dry_run else "pending"
        if not dry_run:
            run.save(update_fields=["status"])

        self.stdout.write("\n=== Migration summary ===")
        for k, v in counts.items():
            self.stdout.write(f"  {k}: {v}")
        estimates_written = counts["estimate"]
        estimate_parent_skip = counts["estimate_parent_skip"]
        total_hours = round(total_hours, 2)
        self.stdout.write(
            f"Estimates: {estimates_written} issues written, total {total_hours} hours, "
            f"{estimate_parent_skip} parent estimates rolled-up (not written)"
        )
        if dry_run:
            self.stdout.write("[DRY RUN — no data written]")
        else:
            self.stdout.write(f"MigrationRun #{run.pk} status: {run.status}")

    def _apply_list_tasks(
        self, run, client, list_id, project, workspace,
        state_map, label_map, field_defs,
        mapping_cache, user_cache, bot_user,
        use_auth, dry_run, counts,
        task_to_issue, subtask_parents, all_tasks_raw,
        module=None,
        date_updated_gt=None,
        migrate_attachments=False,
        snapshot_by_list=None,
    ):
        """Write all tasks for a single ClickUp list.

        Tasks come from the snapshot when one is loaded (no ClickUp task paging
        at all), otherwise they are crawled live.
        """
        from plane.clickup_migrate.writers import (
            write_issue, write_issue_assignee, write_issue_label,
            write_module_issue, write_issue_subscriber, write_comment,
            write_attachment, write_custom_fields_to_description,
            write_state,
        )
        from plane.db.models import State

        if snapshot_by_list is not None:
            task_pages = [(snapshot_by_list.get(str(list_id), []), 0)]
        else:
            task_pages = (
                page
                for archived in (False, True)
                for page in client.iter_tasks(
                    list_id, archived=archived, date_updated_gt=date_updated_gt
                )
            )

        for tasks_page, page_num in task_pages:
            for task in tasks_page:
                task_id = str(task.get("id", ""))
                all_tasks_raw[task_id] = task

                # Track subtask parent for pass-2.
                parent_task_id = str((task.get("parent") or ""))
                if parent_task_id:
                    subtask_parents[task_id] = parent_task_id

                # Resolve state — create lazily from the TASK's status.
                # This workspace exposes statuses at space/folder level, so
                # list defs carry none; deriving states from tasks is the
                # only way to preserve real Open/In-Progress/Done fidelity.
                status_obj = task.get("status") or {}
                status_name = status_obj.get("status", "")
                state = state_map.get(status_name)
                if state is None and status_name and not dry_run:
                    group = mapping_cache.status_group(list_id, status_name)
                    has_default = State.all_state_objects.filter(
                        project=project, default=True
                    ).exists()
                    state = write_state(
                        run, project, workspace, list_id,
                        {"status": status_name, "color": status_obj.get("color", "#60646C")},
                        group, is_default=not has_default,
                        user_cache=user_cache, dry_run=dry_run,
                    )
                    if state is not None:
                        state_map[status_name] = state
                        counts["state"] += 1
                if state is None and state_map:
                    state = next(iter(state_map.values()))

                issue = write_issue(
                    run, project, workspace, task, state,
                    mapping_cache, user_cache, dry_run,
                )
                if issue:
                    task_to_issue[task_id] = issue
                counts["issue"] += 1

                if not issue or dry_run:
                    continue

                # Assignees.
                for a in (task.get("assignees") or []):
                    email = (a or {}).get("email")
                    assignee = user_cache.resolve(email)
                    write_issue_assignee(issue, assignee, dry_run)
                    counts["assignee"] += 1

                # Labels (tags).
                for tag in (task.get("tags") or []):
                    label = label_map.get(tag.get("name", ""))
                    if label:
                        write_issue_label(issue, label, bot_user, dry_run)
                        counts["label_link"] += 1

                # Module membership.
                if module:
                    write_module_issue(module, issue, bot_user, dry_run)
                    counts["module_issue"] += 1

                # Watchers → IssueSubscriber.
                for w in (task.get("watchers") or []):
                    email = (w or {}).get("email")
                    sub = user_cache.resolve(email)
                    write_issue_subscriber(issue, sub, bot_user, dry_run)
                    counts["subscriber"] += 1

                # Custom fields → description table + archive.
                write_custom_fields_to_description(
                    issue, task, field_defs, mapping_cache, bot_user, dry_run
                )

                # Attachments (see _resolve_attachments for the issue-#6
                # list-endpoint detail-fetch rationale).
                for att in self._resolve_attachments(
                    task, task_id, client, migrate_attachments, counts
                ):
                    write_attachment(run, issue, workspace, att, client, use_auth, bot_user, dry_run)
                    counts["attachment"] += 1

                # Comments (with cursor resumption).
                # H1: MigrationCursor.get_or_create only in non-dry-run.
                from plane.clickup_migrate.models import MigrationCursor
                if dry_run:
                    # Dry-run: iterate all comments without persisting cursor state.
                    for comments, _, _ in client.iter_comments(task_id, start_id=None):
                        counts["comment"] += len(comments)
                        for comment in comments:
                            counts["comment"] += len(comment.get("replies") or [])
                else:
                    cursor_obj, _ = MigrationCursor.objects.get_or_create(
                        run=run,
                        entity_type="comments",
                        container_id=task_id,
                        defaults={"cursor_token": None, "done": False},
                    )
                    if cursor_obj.done:
                        continue

                    start_id = cursor_obj.cursor_token
                    for comments, _, next_cursor in client.iter_comments(task_id, start_id=start_id):
                        for comment in comments:
                            parent_comment = write_comment(
                                run, issue, workspace, comment, user_cache,
                                parent_comment=None, dry_run=dry_run,
                            )
                            counts["comment"] += 1
                            # Replies.
                            for reply in (comment.get("replies") or []):
                                write_comment(
                                    run, issue, workspace, reply, user_cache,
                                    parent_comment=parent_comment, dry_run=dry_run,
                                )
                                counts["comment"] += 1

                        # Checkpoint cursor.
                        cursor_obj.cursor_token = next_cursor
                        cursor_obj.save(update_fields=["cursor_token"])

                    cursor_obj.done = True
                    cursor_obj.save(update_fields=["done"])
