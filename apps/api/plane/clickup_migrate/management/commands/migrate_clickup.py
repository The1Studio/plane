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

import logging
import os
import sys
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
        parser.add_argument("--dry-run", action="store_true", help="No .save() calls; emit counts only")
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

        from plane.clickup_migrate.client import ClickUpClient
        from plane.clickup_migrate.models import EmailCoverage, MigrationRun
        from plane.db.models import User, Workspace

        client = ClickUpClient(token=token, team_id=team_id)

        # ── workspace + bot user ──────────────────────────────────────
        workspace = Workspace.objects.filter(slug__isnull=False).first()
        if not workspace:
            raise CommandError("No Workspace found in the database. Did SP0 run?")

        try:
            bot_user = User.objects.get(email__iexact=bot_email)
        except User.DoesNotExist:
            raise CommandError(
                f"Bot user '{bot_email}' not found. "
                "Create a 'ClickUp Migration' user in Plane before running the migration."
            )

        # ── MigrationRun ──────────────────────────────────────────────
        if run_id:
            try:
                run = MigrationRun.objects.get(pk=run_id)
                self.stdout.write(f"Resuming MigrationRun #{run.pk}")
            except MigrationRun.DoesNotExist:
                raise CommandError(f"MigrationRun #{run_id} not found.")
        else:
            run = MigrationRun.objects.create(
                space_ids=space_ids,
                dry_run=dry_run,
                status="pending",
            )
            self.stdout.write(f"Created MigrationRun #{run.pk}")

        # ── dispatch ──────────────────────────────────────────────────
        if options["plan"]:
            self._run_plan(run, client, workspace, bot_user, space_ids, dry_run, review_dir)
        else:
            self._run_apply(run, client, workspace, bot_user, space_ids, dry_run)

    # ─────────────────────────────────────────────────────────────────
    # Phase 3 — --plan
    # ─────────────────────────────────────────────────────────────────

    def _run_plan(self, run, client, workspace, bot_user, space_ids, dry_run, review_dir):
        import json
        import os
        import anthropic as ant

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

            EmailCoverage.objects.get_or_create(
                run=run,
                clickup_email=email,
                defaults={"plane_user_id": plane_uid, "signed_off": False},
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
                for tasks_page, _ in client.iter_tasks(lid, archived=False):
                    all_tasks.extend(tasks_page)
                for tasks_page, _ in client.iter_tasks(lid, archived=True):
                    all_tasks.extend(tasks_page)
            # Folders + their lists.
            for folder in client.get_folders(sid):
                for lst in client.get_lists_in_folder(folder["id"]):
                    lid = lst["id"]
                    field_defs_by_list[lid] = client.get_field_defs(lid)
                    for tasks_page, _ in client.iter_tasks(lid, archived=False):
                        all_tasks.extend(tasks_page)
                    for tasks_page, _ in client.iter_tasks(lid, archived=True):
                        all_tasks.extend(tasks_page)

        self.stdout.write(f"Collected {len(all_tasks)} tasks")

        # Deduplicate tasks by id.
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for t in all_tasks:
            tid = t.get("id", "")
            if tid not in seen_ids:
                seen_ids.add(tid)
                deduped.append(t)
        all_tasks = deduped

        distinct_statuses = collect_distinct_statuses(all_tasks)
        distinct_fields = collect_distinct_custom_field_defs(field_defs_by_list)
        self.stdout.write(f"Distinct statuses: {len(distinct_statuses)}, custom fields: {len(distinct_fields)}")

        # ── Anthropic Batches ─────────────────────────────────────────
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or ""
        if not anthropic_key:
            raise CommandError("ANTHROPIC_API_KEY environment variable required for --plan.")

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
    # Phases 4a / 4b / 5 — --apply
    # ─────────────────────────────────────────────────────────────────

    def _run_apply(self, run, client, workspace, bot_user, space_ids, dry_run):
        from plane.clickup_migrate.writers import (
            UserCache,
            MappingCache,
            check_apply_gate,
            write_project,
            write_state,
            write_label,
            write_module,
            write_issue,
            write_issue_assignee,
            write_issue_label,
            write_module_issue,
            write_issue_subscriber,
            write_comment,
            write_subtask_parent,
            write_issue_relation,
            write_attachment,
            write_custom_fields_to_description,
        )
        from plane.db.models import Issue

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

        use_auth: bool = True  # default; caller can override via env

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
            "attachment": 0, "relation": 0, "parent_link": 0,
        }

        # Map ClickUp task_id → Plane Issue (for pass-2 + junctions).
        task_to_issue: dict[str, object] = {}
        # Map ClickUp task_id → parent_task_id.
        subtask_parents: dict[str, str] = {}
        # Collect all raw tasks for pass-2 relations.
        all_tasks_raw: dict[str, dict] = {}

        # ── per-space traversal ───────────────────────────────────────
        for space in spaces:
            sid = space["id"]
            space_tags = space.get("statuses") or []

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
                if project and not default_set:
                    from plane.db.models import State
                    State.all_state_objects.create(
                        project=project,
                        workspace=workspace,
                        name="Backlog",
                        color="#60646C",
                        group="backlog",
                        default=True,
                        created_by_id=bot_user.id,
                        updated_by_id=bot_user.id,
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
                    )

        # ── pass-2: subtask parents ───────────────────────────────────
        self.stdout.write(f"Pass-2: linking {len(subtask_parents)} subtask parent(s) …")
        for child_id, parent_id in subtask_parents.items():
            ok = write_subtask_parent(run, child_id, parent_id, dry_run)
            if ok:
                counts["parent_link"] += 1

        # ── pass-2: issue relations ───────────────────────────────────
        for task_id, task in all_tasks_raw.items():
            deps = task.get("dependencies") or []
            for dep in deps:
                dep_task_id = str(dep.get("task_id", ""))
                dep_type = dep.get("type", "waiting_on")
                if dep_task_id:
                    project_for_rel = getattr(task_to_issue.get(task_id), "project", None)
                    ws_for_rel = workspace
                    write_issue_relation(
                        run, dep_type, task_id, dep_task_id,
                        ws_for_rel, project_for_rel, bot_user, dry_run,
                    )
                    counts["relation"] += 1

        run.status = "done" if not dry_run else "pending"
        if not dry_run:
            run.save(update_fields=["status"])

        self.stdout.write("\n=== Migration summary ===")
        for k, v in counts.items():
            self.stdout.write(f"  {k}: {v}")
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
    ):
        """Extract and write all tasks from a single ClickUp list."""
        from plane.clickup_migrate.writers import (
            write_issue, write_issue_assignee, write_issue_label,
            write_module_issue, write_issue_subscriber, write_comment,
            write_attachment, write_custom_fields_to_description,
        )

        for archived in (False, True):
            for tasks_page, page_num in client.iter_tasks(list_id, archived=archived):
                for task in tasks_page:
                    task_id = str(task.get("id", ""))
                    all_tasks_raw[task_id] = task

                    # Track subtask parent for pass-2.
                    parent_task_id = str((task.get("parent") or ""))
                    if parent_task_id:
                        subtask_parents[task_id] = parent_task_id

                    # Resolve state.
                    status_name = (task.get("status") or {}).get("status", "")
                    state = state_map.get(status_name)
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

                    # Attachments.
                    for att in (task.get("attachments") or []):
                        write_attachment(run, issue, workspace, att, client, use_auth, bot_user, dry_run)
                        counts["attachment"] += 1

                    # Comments (with cursor resumption).
                    from plane.clickup_migrate.models import MigrationCursor
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
                        if not dry_run:
                            cursor_obj.save(update_fields=["cursor_token"])

                    if not dry_run:
                        cursor_obj.done = True
                        cursor_obj.save(update_fields=["done"])
