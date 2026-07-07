# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — Phase 4a/4b/5 entity writers.
#
# FK-safe write order:
#   verify_users → projects (+identifier) → states → labels → modules
#   → issues (parent=null, serial per project) → junctions
#   → comments (+replies) → attachments
#   pass-2: subtask parents + issue relations
#
# CRITICAL constraints (verified against Plane source):
#
# C1 — AUTHORSHIP: BaseModel.save() (db/models/base.py:23) assigns
#   created_by_id ONLY inside `if not disable_auto_set_user:`. Passing
#   disable_auto_set_user=True therefore SKIPS the assignment and leaves
#   authorship NULL (crum.get_current_user() is always None in a management
#   command, so there is no fallback). The correct pattern is to pass
#   created_by_id and let disable_auto_set_user default to False:
#     instance.save(created_by_id=author.id)
#   NEVER put created_by_id/updated_by_id in update_or_create(defaults={}).
#   For update_or_create we must post-save re-call .save(created_by_id=...).
#
# C2 — State.unique(name, project, deleted_at IS NULL): upsert by
#   (project, name, group) not per-list external_id to avoid collisions.
#
# C3 — Relations pass-2: resolve project from the LEDGER (Issue lookup),
#   not the volatile in-memory task_to_issue map which is empty on resume.
#
# H2 — completed_at: Issue.save() forces completed_at=now() on completed
#   states; we ALWAYS set it in the post-save .update() (backdated or None)
#   unconditionally so the timestamp reflects ClickUp, not migration time.
#
# M4 — Attachment size mismatch → STATUS_ERROR in ledger (not just warning).

import io
import json
import logging
import re
from typing import Optional
from uuid import uuid4

from django.db import transaction

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

EXTERNAL_SOURCE = "clickup"

_PRIO_FALLBACK = {
    "urgent": "urgent",
    "high": "high",
    "normal": "medium",
    "low": "low",
    "no priority": "none",
}


def _record_upsert(
    run,
    source_type: str,
    source_id: str,
    plane_type: str,
    plane_id: str,
    status: str,
    bytes_val: int = 0,
) -> None:
    """Write or update a MigrationRecord inside the caller's atomic block."""
    from plane.clickup_migrate.models import MigrationRecord

    MigrationRecord.objects.update_or_create(
        run=run,
        source_type=source_type,
        source_id=source_id,
        defaults={
            "plane_type": plane_type,
            "plane_id": str(plane_id),
            "status": status,
            "bytes": bytes_val,
            "error": "",
        },
    )


def _record_error(run, source_type: str, source_id: str, error: str) -> None:
    from plane.clickup_migrate.models import MigrationRecord

    MigrationRecord.objects.update_or_create(
        run=run,
        source_type=source_type,
        source_id=source_id,
        defaults={
            "plane_type": "",
            "plane_id": "",
            "status": MigrationRecord.STATUS_ERROR,
            "error": error[:2000],
        },
    )


def _ledger_done(run, source_type: str, source_id: str) -> Optional[str]:
    """Return plane_id if already successfully migrated, else None."""
    from plane.clickup_migrate.models import MigrationRecord

    try:
        rec = MigrationRecord.objects.get(
            run=run,
            source_type=source_type,
            source_id=source_id,
            status__in=(
                MigrationRecord.STATUS_CREATED,
                MigrationRecord.STATUS_UPDATED,
                MigrationRecord.STATUS_SKIPPED,
            ),
        )
        return rec.plane_id
    except MigrationRecord.DoesNotExist:
        return None


def _verify_plane_object_exists(model_class, pk: str) -> bool:
    """Check that the Plane object with this pk still exists (not soft-deleted)."""
    try:
        model_class.all_objects.get(pk=pk)
        return True
    except model_class.DoesNotExist:
        return False


def _ts_ms_to_dt(ts_ms_str) -> Optional[object]:
    """Convert a ClickUp millisecond epoch string to a timezone-aware datetime."""
    if not ts_ms_str:
        return None
    try:
        from django.utils import timezone
        return timezone.datetime.fromtimestamp(int(ts_ms_str) / 1000, tz=timezone.utc)
    except (ValueError, OSError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────
# User resolution
# ─────────────────────────────────────────────────────────────────────

class UserCache:
    """Email → User resolver with bot fallback.

    Resolves via email__iexact matching (plan M3).
    bot_user is the 'ClickUp Migration' bot account.
    """

    def __init__(self, bot_user):
        from plane.db.models import User
        self._cache: dict[str, Optional[object]] = {}
        self._User = User
        self.bot_user = bot_user

    def resolve(self, email: Optional[str]) -> object:
        """Return the Plane User for email, or the bot user if unmatched."""
        if not email:
            return self.bot_user
        email_lower = email.lower()
        if email_lower in self._cache:
            return self._cache[email_lower] or self.bot_user
        try:
            user = self._User.objects.get(email__iexact=email_lower)
            self._cache[email_lower] = user
            return user
        except self._User.DoesNotExist:
            self._cache[email_lower] = None
            return self.bot_user


# ─────────────────────────────────────────────────────────────────────
# Gate check
# ─────────────────────────────────────────────────────────────────────

def check_apply_gate(run) -> list[str]:
    """Return a list of blocker messages; empty = gate passes.

    --apply MUST be refused unless:
    1. Every MappingTable row for this run has approved=True.
    2. Every EmailCoverage row for this run has signed_off=True.
    """
    from plane.clickup_migrate.models import MappingTable, EmailCoverage

    blockers = []
    unapproved = MappingTable.objects.filter(run=run, approved=False).count()
    if unapproved:
        blockers.append(
            f"{unapproved} MappingTable row(s) still unapproved — approve all before --apply."
        )

    unsigned = EmailCoverage.objects.filter(run=run, signed_off=False).count()
    if unsigned:
        blockers.append(
            f"{unsigned} EmailCoverage row(s) unsigned — sign off all before --apply."
        )

    return blockers


# ─────────────────────────────────────────────────────────────────────
# Mapping lookups (apply phase — NO Anthropic calls)
# ─────────────────────────────────────────────────────────────────────

class MappingCache:
    """In-memory cache of approved MappingTable rows for the apply phase."""

    def __init__(self, run):
        from plane.clickup_migrate.models import MappingTable

        self._status: dict[str, str] = {}
        self._priority: dict[str, str] = {}
        self._fields: dict[str, str] = {}

        for row in MappingTable.objects.filter(run=run, approved=True):
            if row.kind == MappingTable.KIND_STATUS:
                self._status[row.source_key] = row.target_value
            elif row.kind == MappingTable.KIND_PRIORITY:
                self._priority[json.loads(row.source_key)] = row.target_value
            elif row.kind == MappingTable.KIND_CUSTOM_FIELD:
                self._fields[json.loads(row.source_key)] = row.target_value

    def status_group(self, list_id: str, status_name: str) -> str:
        from plane.clickup_migrate.normalize import make_status_key
        key = make_status_key(list_id, status_name)
        return self._status.get(key, "backlog")

    def priority(self, clickup_prio: str) -> str:
        return self._priority.get(clickup_prio, _PRIO_FALLBACK.get(clickup_prio, "none"))

    def field_suggestion(self, field_id: str) -> str:
        return self._fields.get(field_id, "")


# ─────────────────────────────────────────────────────────────────────
# Project + State + Label + Module writers
# ─────────────────────────────────────────────────────────────────────

def write_project(run, workspace, clickup_folder_or_list: dict, user_cache: UserCache, dry_run: bool) -> Optional[object]:
    """Write a single Project.

    C1 fix: removed created_by_id from defaults; post-save .save(created_by_id=...)
    with disable_auto_set_user left False so the assignment is honored.
    """
    from plane.clickup_migrate.models import MigrationRecord
    from plane.db.models import Project, ProjectIdentifier

    src_id = str(clickup_folder_or_list["id"])
    name = clickup_folder_or_list.get("name", "")[:255]
    identifier_raw = re.sub(r"[^A-Z0-9]", "", name.upper())[:12] or src_id[:6].upper()

    if dry_run:
        logger.info("[dry-run] would create/update project: %s", name)
        return None

    with transaction.atomic():
        project, created = Project.all_objects.update_or_create(
            external_source=EXTERNAL_SOURCE,
            external_id=src_id,
            defaults={
                "workspace": workspace,
                "name": name,
                "identifier": identifier_raw,
            },
        )
        # C1: set authorship via save kwargs, not defaults.
        project.save(
            created_by_id=user_cache.bot_user.id,
        )
        ProjectIdentifier.objects.get_or_create(
            project=project,
            defaults={
                "workspace": workspace,
                "name": identifier_raw,
            },
        )
        status = MigrationRecord.STATUS_CREATED if created else MigrationRecord.STATUS_UPDATED
        _record_upsert(run, "folder", src_id, "Project", str(project.id), status)
    return project


def write_state(
    run,
    project,
    workspace,
    list_id: str,
    clickup_status: dict,
    group: str,
    is_default: bool,
    user_cache: UserCache,
    dry_run: bool,
) -> Optional[object]:
    """Write a State for a project.

    C2 fix: upsert on (project, name) not on per-list external_id.
    Two ClickUp lists in the same Folder with status "Open" would otherwise
    violate State's unique(name, project, deleted_at IS NULL) constraint.
    external_id/external_source are written after upsert (metadata only).
    """
    from plane.clickup_migrate.models import MigrationRecord
    from plane.db.models import State

    status_name = (
        clickup_status.get("status", "") if isinstance(clickup_status, dict) else str(clickup_status)
    )
    color = (
        clickup_status.get("color", "#60646C") if isinstance(clickup_status, dict) else "#60646C"
    )
    # External id still encodes the list for tracing, but upsert key is (project, name).
    per_list_ext_id = f"{list_id}_{status_name}"

    if dry_run:
        logger.info("[dry-run] would create/update state: %s / %s", project.name if project else "?", status_name)
        return None

    with transaction.atomic():
        # C2: key on (project, name) — mirrors the DB unique constraint.
        state, created = State.all_state_objects.update_or_create(
            project=project,
            name=status_name[:255],
            defaults={
                "workspace": workspace,
                "color": color[:255],
                "group": group,
                "default": is_default,
                "external_source": EXTERNAL_SOURCE,
                "external_id": per_list_ext_id,
            },
        )
        # C1: authorship via save kwargs.
        state.save(
            created_by_id=user_cache.bot_user.id,
        )
        status_str = MigrationRecord.STATUS_CREATED if created else MigrationRecord.STATUS_UPDATED
        _record_upsert(run, "status", per_list_ext_id, "State", str(state.id), status_str)
    return state


def write_label(run, workspace, project, clickup_tag: dict, user_cache: UserCache, dry_run: bool) -> Optional[object]:
    """Write a Label (ClickUp tag → Plane label).

    C1 fix: authorship via save kwargs.
    """
    from plane.clickup_migrate.models import MigrationRecord
    from plane.db.models import Label

    src_id = str(clickup_tag.get("name", ""))
    if not src_id:
        # No name → no stable external_id; skip (avoids empty-key collision
        # on the cu_label_ext_idx partial unique index).
        return None
    name = src_id[:255]
    color = (clickup_tag.get("tag_bg") or "#60646C")[:255]

    if dry_run:
        logger.info("[dry-run] would create/update label: %s", name)
        return None

    with transaction.atomic():
        label, created = Label.all_objects.update_or_create(
            external_source=EXTERNAL_SOURCE,
            external_id=src_id,
            project=project,
            workspace=workspace,
            defaults={
                "name": name,
                "color": color,
            },
        )
        # C1: authorship via save kwargs.
        label.save(
            created_by_id=user_cache.bot_user.id,
        )
        status = MigrationRecord.STATUS_CREATED if created else MigrationRecord.STATUS_UPDATED
        _record_upsert(run, "tag", src_id, "Label", str(label.id), status)
    return label


def write_module(run, project, workspace, clickup_list: dict, user_cache: UserCache, dry_run: bool) -> Optional[object]:
    """Write a Module (ClickUp list inside a folder → Plane module).

    C1 fix: authorship via save kwargs.
    """
    from plane.clickup_migrate.models import MigrationRecord
    from plane.db.models import Module

    src_id = str(clickup_list["id"])
    name = clickup_list.get("name", "")[:255]

    if dry_run:
        logger.info("[dry-run] would create/update module: %s", name)
        return None

    with transaction.atomic():
        module, created = Module.all_objects.update_or_create(
            external_source=EXTERNAL_SOURCE,
            external_id=src_id,
            project=project,
            defaults={
                "workspace": workspace,
                "name": name,
                "status": "planned",
            },
        )
        # C1: authorship via save kwargs.
        module.save(
            created_by_id=user_cache.bot_user.id,
        )
        status = MigrationRecord.STATUS_CREATED if created else MigrationRecord.STATUS_UPDATED
        _record_upsert(run, "list", src_id, "Module", str(module.id), status)
    return module


# ─────────────────────────────────────────────────────────────────────
# Issue writer
# ─────────────────────────────────────────────────────────────────────

def write_issue(
    run,
    project,
    workspace,
    clickup_task: dict,
    state,
    mapping_cache: MappingCache,
    user_cache: UserCache,
    dry_run: bool,
) -> Optional[object]:
    """Write a single Issue (parent link deferred to pass-2).

    NEVER bulk_create Issue — Issue.save() holds an advisory lock and
    creates IssueSequence (issue.py:205-235).

    C1 fix: authorship via .save(created_by_id=...).
    H2 fix: always write completed_at in the post-save .update(), backdated
      or explicitly None, so the timestamp reflects ClickUp not migration time.
    """
    from plane.clickup_migrate.convert import convert_markdown
    from plane.clickup_migrate.models import MigrationRecord
    from plane.db.models import Issue

    src_id = str(clickup_task["id"])
    name = clickup_task.get("name", "")[:255]
    priority_raw = (
        clickup_task.get("priority", {}).get("priority", "none")
        if isinstance(clickup_task.get("priority"), dict)
        else "none"
    )
    priority = mapping_cache.priority(priority_raw)

    md = clickup_task.get("markdown_description") or clickup_task.get("description") or ""
    conv = convert_markdown(md)

    creator_email = (clickup_task.get("creator") or {}).get("email")
    author = user_cache.resolve(creator_email)

    if dry_run:
        logger.info("[dry-run] would create/update issue: %s", name)
        return None

    existing_plane_id = _ledger_done(run, "task", src_id)
    if existing_plane_id:
        if _verify_plane_object_exists(Issue, existing_plane_id):
            _record_upsert(run, "task", src_id, "Issue", existing_plane_id, MigrationRecord.STATUS_SKIPPED)
            return Issue.all_objects.get(pk=existing_plane_id)

    with transaction.atomic():
        issue, created = Issue.all_objects.update_or_create(
            external_source=EXTERNAL_SOURCE,
            external_id=src_id,
            project=project,
            defaults={
                "workspace": workspace,
                "name": name,
                "description_json": conv.description_json,
                "description_html": conv.description_html,
                "description_stripped": conv.description_stripped,
                "state": state,
                "priority": priority,
                "parent": None,  # pass-2 links subtask parents
            },
        )
        # C1: set authorship after upsert via save kwargs (mixins.py:23-44).
        issue.save(
            created_by_id=author.id,
        )

        # H2 + C5: always backdate created_at, updated_at, AND completed_at.
        # Issue.save() forces completed_at=now() for completed states (issue.py:198-203);
        # we unconditionally overwrite it here — either with the ClickUp date or None.
        date_created = _ts_ms_to_dt(clickup_task.get("date_created"))
        date_updated = _ts_ms_to_dt(clickup_task.get("date_updated"))
        is_completed = state and state.group == "completed"
        completed_at = date_updated if is_completed else None

        dates: dict = {"completed_at": completed_at}  # always written (H2)
        if date_created:
            dates["created_at"] = date_created
        if date_updated:
            dates["updated_at"] = date_updated

        Issue.all_objects.filter(pk=issue.pk).update(**dates)

        rec_status = MigrationRecord.STATUS_CREATED if created else MigrationRecord.STATUS_UPDATED
        _record_upsert(run, "task", src_id, "Issue", str(issue.id), rec_status)

    return issue


# ─────────────────────────────────────────────────────────────────────
# Junction writers
# C1 fix applied to all: get_or_create returns (obj, created); if created,
#   we call obj.save(created_by_id=...) (disable_auto_set_user left False).
# ─────────────────────────────────────────────────────────────────────

def write_issue_assignee(issue, assignee_user, dry_run: bool) -> None:
    from plane.db.models import IssueAssignee
    if dry_run:
        return
    obj, created = IssueAssignee.all_objects.get_or_create(
        issue=issue,
        assignee=assignee_user,
        defaults={
            "project": issue.project,
            "workspace": issue.workspace,
        },
    )
    if created:
        obj.save(created_by_id=assignee_user.id)


def write_issue_label(issue, label, bot_user, dry_run: bool) -> None:
    from plane.db.models import IssueLabel
    if dry_run:
        return
    obj, created = IssueLabel.all_objects.get_or_create(
        issue=issue,
        label=label,
        defaults={
            "project": issue.project,
            "workspace": issue.workspace,
        },
    )
    if created:
        obj.save(created_by_id=bot_user.id)


def write_module_issue(module, issue, bot_user, dry_run: bool) -> None:
    from plane.db.models import ModuleIssue
    if dry_run:
        return
    obj, created = ModuleIssue.all_objects.get_or_create(
        module=module,
        issue=issue,
        defaults={
            "project": issue.project,
            "workspace": issue.workspace,
        },
    )
    if created:
        obj.save(created_by_id=bot_user.id)


def write_issue_subscriber(issue, subscriber_user, bot_user, dry_run: bool) -> None:
    """Watcher → IssueSubscriber."""
    from plane.db.models import IssueSubscriber
    if dry_run:
        return
    obj, created = IssueSubscriber.all_objects.get_or_create(
        issue=issue,
        subscriber=subscriber_user,
        defaults={
            "project": issue.project,
            "workspace": issue.workspace,
        },
    )
    if created:
        obj.save(created_by_id=bot_user.id)


# ─────────────────────────────────────────────────────────────────────
# Comment writer
# ─────────────────────────────────────────────────────────────────────

def write_comment(
    run,
    issue,
    workspace,
    clickup_comment: dict,
    user_cache: UserCache,
    parent_comment=None,
    dry_run: bool = False,
) -> Optional[object]:
    """Write an IssueComment.

    IssueComment.save() auto-creates a Description — do NOT create it manually.
    parent= sets the threaded-reply FK (IssueComment.parent, issue.py:467).

    C1 fix: authorship via save kwargs after upsert.
    """
    from plane.clickup_migrate.convert import convert_markdown
    from plane.clickup_migrate.models import MigrationRecord
    from plane.db.models import IssueComment

    src_id = str(clickup_comment.get("id", ""))
    text = clickup_comment.get("comment_text", "") or ""
    author_email = (clickup_comment.get("user") or {}).get("email")
    author = user_cache.resolve(author_email)
    conv = convert_markdown(text)

    if dry_run:
        logger.info(
            "[dry-run] would create/update comment %s on issue %s",
            src_id,
            issue.pk if issue else "?",
        )
        return None

    existing = _ledger_done(run, "comment", src_id)
    if existing:
        if _verify_plane_object_exists(IssueComment, existing):
            _record_upsert(run, "comment", src_id, "IssueComment", existing, MigrationRecord.STATUS_SKIPPED)
            return IssueComment.all_objects.get(pk=existing)

    with transaction.atomic():
        comment, created = IssueComment.all_objects.update_or_create(
            external_source=EXTERNAL_SOURCE,
            external_id=src_id,
            issue=issue,
            defaults={
                "project": issue.project,
                "workspace": workspace,
                "comment_json": conv.description_json,
                "comment_html": conv.description_html,
                "actor_id": author.id,
                "parent": parent_comment,
            },
        )
        # C1: authorship via save kwargs; IssueComment.save() also updates
        # the auto-created Description's created_by (issue.py:488).
        comment.save(
            created_by_id=author.id,
        )

        # Backdate comment timestamp (mixins.py:19-20).
        ts = _ts_ms_to_dt(clickup_comment.get("date"))
        if ts:
            IssueComment.all_objects.filter(pk=comment.pk).update(created_at=ts, updated_at=ts)

        rec_status = MigrationRecord.STATUS_CREATED if created else MigrationRecord.STATUS_UPDATED
        _record_upsert(run, "comment", src_id, "IssueComment", str(comment.id), rec_status)

    return comment


# ─────────────────────────────────────────────────────────────────────
# Pass-2: subtask parent links + IssueRelations
# ─────────────────────────────────────────────────────────────────────

def write_subtask_parent(run, child_task_id: str, parent_task_id: str, dry_run: bool) -> bool:
    """Set Issue.parent for a subtask.  Orphans (parent not in ledger) are logged."""
    from plane.db.models import Issue

    parent_plane_id = _ledger_done(run, "task", parent_task_id)
    child_plane_id = _ledger_done(run, "task", child_task_id)

    if not parent_plane_id:
        logger.warning("Orphan subtask %s — parent %s not migrated", child_task_id, parent_task_id)
        return False
    if not child_plane_id:
        logger.warning("Subtask %s not migrated — cannot link parent", child_task_id)
        return False
    if dry_run:
        return True

    Issue.all_objects.filter(pk=child_plane_id).update(parent_id=parent_plane_id)
    return True


def write_issue_relation(
    run,
    clickup_relation_type: str,
    source_task_id: str,
    target_task_id: str,
    workspace,
    bot_user,
    dry_run: bool,
) -> bool:
    """Write a canonical IssueRelation row.

    Replicates get_actual_relation() canonicalization from
    plane/utils/issue_relation_mapper.py:19-32.

    ClickUp relation types → Plane:
      'waiting_on'  → blocked_by  (issue=waiter, related=blocker)
      'blocking'    → blocked_by  (issue=target/blocker, related=source/blocked; swap)
      'linked'      → relates_to

    C3 fix: resolve project from the Issue object fetched from the DB via the
    ledger plane_id — NOT from the volatile in-memory task_to_issue map, which
    is empty on a resumed run.  Project is a required FK on IssueRelation via
    ProjectBaseModel.save() (workspace_%(class)s).
    """
    from plane.db.models import Issue, IssueRelation
    from plane.utils.issue_relation_mapper import get_actual_relation

    source_plane_id = _ledger_done(run, "task", source_task_id)
    target_plane_id = _ledger_done(run, "task", target_task_id)

    if not source_plane_id or not target_plane_id:
        logger.warning(
            "Relation skip: source=%s target=%s — one not migrated",
            source_task_id,
            target_task_id,
        )
        return False

    clickup_to_plane = {
        "waiting_on": "blocked_by",
        "blocking": "blocked_by",
        "linked": "relates_to",
        "relates_to": "relates_to",
    }
    raw_relation = clickup_to_plane.get(clickup_relation_type, "relates_to")
    actual_relation = get_actual_relation(raw_relation)

    # For 'blocking': swap issue/related so the canonical direction is correct.
    if clickup_relation_type == "blocking":
        issue_plane_id = target_plane_id
        related_plane_id = source_plane_id
    else:
        issue_plane_id = source_plane_id
        related_plane_id = target_plane_id

    if dry_run:
        return True

    # C3: resolve project from the DB — the in-memory map is empty on resume.
    try:
        issue_obj = Issue.all_objects.select_related("project", "workspace").get(pk=issue_plane_id)
    except Issue.DoesNotExist:
        logger.warning("Relation skip: issue %s not found in DB", issue_plane_id)
        return False

    with transaction.atomic():
        obj, created = IssueRelation.all_objects.get_or_create(
            issue_id=issue_plane_id,
            related_issue_id=related_plane_id,
            defaults={
                "project": issue_obj.project,
                "workspace": issue_obj.workspace,
                "relation_type": actual_relation,
            },
        )
        if created:
            # C1: authorship via save kwargs.
            obj.save(created_by_id=bot_user.id)
    return True


# ─────────────────────────────────────────────────────────────────────
# Phase 5 — Attachments + Custom fields
# ─────────────────────────────────────────────────────────────────────

def write_attachment(
    run,
    issue,
    workspace,
    clickup_attachment: dict,
    client,
    use_auth: bool,
    bot_user,
    dry_run: bool,
) -> Optional[object]:
    """Download and re-host a ClickUp attachment into MinIO via S3Storage.

    Recipe (plan P5 / C4):
      1. Ledger-check before download.
      2. download → S3Storage().upload_file → FileAsset.create(is_uploaded=True).
      3. Read back stored size; assert == Content-Length.
      4. Record bytes in MigrationRecord.

    C1 fix: FileAsset is a BaseModel — its .create() calls .save() internally.
    We post-save re-call .save(created_by_id=...) to set authorship correctly.

    M4 fix: size mismatch → STATUS_ERROR in ledger so reconciliation catches
    a truncated upload (not just a logger.warning).
    """
    from plane.clickup_migrate.models import MigrationRecord
    from plane.db.models import FileAsset
    from plane.settings.storage import S3Storage

    att_id = str(clickup_attachment.get("id", ""))
    url = clickup_attachment.get("url", "")
    filename = clickup_attachment.get("title", f"attachment-{att_id}")

    existing = _ledger_done(run, "attachment", att_id)
    if existing:
        if _verify_plane_object_exists(FileAsset, existing):
            _record_upsert(run, "attachment", att_id, "FileAsset", existing, MigrationRecord.STATUS_SKIPPED)
            return FileAsset.all_objects.get(pk=existing)

    if dry_run:
        logger.info("[dry-run] would download attachment %s → %s", att_id, filename)
        return None

    try:
        resp = client.download_attachment(url, use_auth=use_auth)
        content_length = int(resp.headers.get("Content-Length", 0))
        content_type = resp.headers.get("Content-Type", "application/octet-stream")

        from plane.utils.path_validator import sanitize_filename
        safe_name = sanitize_filename(filename) or uuid4().hex
        asset_key = f"{workspace.id}/{uuid4().hex}-{safe_name}"

        storage = S3Storage()
        file_obj = io.BytesIO(resp.content)
        ok = storage.upload_file(file_obj, asset_key, content_type=content_type)
        if not ok:
            _record_error(run, "attachment", att_id, "S3 upload failed")
            return None

        # Read back stored size.
        try:
            stored_meta = storage.s3_client.head_object(
                Bucket=storage.aws_storage_bucket_name,
                Key=asset_key,
            )
            stored_size = stored_meta.get("ContentLength", 0)
        except Exception:
            stored_size = content_length

        # M4: size mismatch → STATUS_ERROR so reconciliation catches truncated uploads.
        if content_length and stored_size != content_length:
            msg = (
                f"Attachment {att_id} size mismatch: expected {content_length}, stored {stored_size}"
            )
            logger.error(msg)
            _record_error(run, "attachment", att_id, msg)
            return None

        with transaction.atomic():
            # FileAsset inherits BaseModel; .create() calls .save() which clears
            # authorship via crum.  Re-call .save(created_by_id=...) to set it
            # (disable_auto_set_user left False so the assignment is honored).
            asset = FileAsset.all_objects.create(
                workspace=workspace,
                project=issue.project,
                issue=issue,
                asset=asset_key,
                size=stored_size,
                is_uploaded=True,
                entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
                entity_identifier=str(issue.id),
                external_source=EXTERNAL_SOURCE,
                external_id=att_id,
            )
            asset.save(created_by_id=bot_user.id)
            _record_upsert(
                run, "attachment", att_id, "FileAsset", str(asset.id),
                MigrationRecord.STATUS_CREATED, bytes_val=stored_size,
            )

        return asset

    except Exception as exc:
        _record_error(run, "attachment", att_id, str(exc))
        logger.error("Attachment %s failed: %s", att_id, exc)
        return None


def write_custom_fields_to_description(
    issue,
    clickup_task: dict,
    field_defs: dict[str, dict],
    mapping_cache: MappingCache,
    bot_user,
    dry_run: bool,
) -> Optional[str]:
    """Append custom fields as a Markdown table to the issue description.

    Resolves dropdown/label ids → names via type_config.
    Stores raw JSON + computed Markdown in ClickupCustomFieldArchive.
    Returns the Markdown table string (or None if no fields).
    """
    from plane.clickup_migrate.models import ClickupCustomFieldArchive
    from plane.db.models import Issue

    custom_fields = clickup_task.get("custom_fields", [])
    if not custom_fields:
        return None

    task_id = str(clickup_task["id"])

    lines = ["", "---", "**Custom Fields**", "", "| Field | Value |", "|---|---|"]
    for cf in custom_fields:
        field_id = cf.get("id", "")
        field_name = cf.get("name", field_id)
        raw_value = cf.get("value")
        field_type = cf.get("type", "")

        # Resolve dropdown/label ids → names via type_config.
        if field_type in ("drop_down", "labels") and raw_value is not None:
            type_config = (field_defs.get(field_id) or {}).get("type_config", {})
            options = type_config.get("options", [])
            opt_map = {str(opt.get("id", "")): opt.get("name", "") for opt in options}
            if isinstance(raw_value, list):
                display = ", ".join(opt_map.get(str(v), str(v)) for v in raw_value)
            else:
                display = opt_map.get(str(raw_value), str(raw_value))
        elif raw_value is None:
            display = ""
        else:
            display = str(raw_value)

        display = display.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {field_name} | {display} |")

    md_table = "\n".join(lines)

    if dry_run:
        return md_table

    # Archive raw JSON.
    ClickupCustomFieldArchive.objects.update_or_create(
        issue_external_id=task_id,
        defaults={
            "raw_json": custom_fields,
            "raw_markdown": md_table,
        },
    )

    # Append the table to the existing description HTML.
    try:
        from plane.clickup_migrate.convert import _md_to_html, _sanitise_html
        extra_html = _sanitise_html(_md_to_html(md_table))
        existing_html = issue.description_html or "<p></p>"
        new_html = existing_html + extra_html
        Issue.all_objects.filter(pk=issue.pk).update(
            description_html=new_html,
            description_stripped=(issue.description_stripped or "") + "\n" + md_table,
        )
    except Exception as exc:
        logger.warning("Failed to append custom fields to issue %s: %s", issue.pk, exc)

    return md_table


# ─────────────────────────────────────────────────────────────────────
# Pass-3: workload estimates (leaf-only)
#
# `time_estimate` is ClickUp's planned-hours field (ms). Reuses the fork's
# native workload.models.WorkloadEstimate — no new model, no new migration.
# Leaf-ness is batch-computed by the caller via
# workload.rollup.parent_issue_ids() (pass-2 parent links must already be
# committed — see migrate_clickup.py pass ordering). A parent's own
# time_estimate is intentionally NOT migrated (rolled up from leaves at read
# time instead); it is only recorded in the ledger as SKIPPED so operators
# can see it was seen and deliberately not written.
# ─────────────────────────────────────────────────────────────────────

def _parse_ms_estimate(raw) -> Optional[int]:
    """Defensively coerce a ClickUp `time_estimate` value to positive int ms.

    The ClickUp OpenAPI spec declares `time_estimate` as `string|null` but
    the live API returns an integer (ms). Accept an `int` or a numeric
    `str`; treat `None`, `0`, negative, or unparseable values as "no
    estimate" (skip). Never raises.
    """
    if raw is None:
        return None
    try:
        ms = int(raw)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return ms


def write_workload_estimate(
    run,
    issue,
    task_id: str,
    raw_ms,
    is_leaf: bool,
    user_cache: UserCache,
    dry_run: bool,
) -> str:
    """Write one WorkloadEstimate for a LEAF issue.

    Returns a status token: "created" | "updated" | "skipped-zero" |
    "skipped-parent" | "clamped". dry_run never writes to the DB but still
    returns the would-be token so the caller's --plan summary tallies
    correctly (mirrors write_subtask_parent's dry-run-returns-True idiom).

    NOTE: leaf-ness is passed IN as `is_leaf` (bool) — the caller
    batch-computes it (workload.rollup.parent_issue_ids()) over the whole
    migrated-issue set. This function does NOT call is_parent() itself
    (avoids a per-issue query).

    created_by distinction (do NOT cargo-cult C1 above): WorkloadEstimate is
    a PLAIN models.Model with no auto-set-user save hook (unlike BaseModel,
    see C1). Authorship is therefore set DIRECTLY in
    update_or_create(defaults=...) below — the core-model post-save
    re-save(created_by_id=...) workaround does not apply here and would be
    wrong.
    """
    from plane.clickup_migrate.models import MigrationRecord
    from plane.workload.aggregation import MAX_HOURS
    from plane.workload.models import WorkloadEstimate

    ms = _parse_ms_estimate(raw_ms)
    if ms is None:
        return "skipped-zero"

    if not is_leaf:
        logger.warning(
            "Issue %s (task %s) carries its own time_estimate but is a "
            "parent — rolled up from leaves, not migrated as its own "
            "estimate",
            issue.pk if issue else "?",
            task_id,
        )
        if not dry_run:
            MigrationRecord.objects.update_or_create(
                run=run,
                source_type="task",
                source_id=str(task_id),
                defaults={
                    "plane_type": "WorkloadEstimate",
                    "plane_id": "",
                    "status": MigrationRecord.STATUS_SKIPPED,
                    "bytes": 0,
                    "error": "parent own-estimate rolled up from leaves",
                },
            )
        return "skipped-parent"

    hours = round(ms / 3_600_000, 2)
    clamped = False
    if hours > MAX_HOURS:
        logger.warning(
            "Issue %s (task %s) time_estimate %s ms exceeds MAX_HOURS "
            "(%s) — clamped",
            issue.pk if issue else "?",
            task_id,
            raw_ms,
            MAX_HOURS,
        )
        hours = MAX_HOURS
        clamped = True

    if dry_run:
        logger.info(
            "[dry-run] would create/update workload estimate: issue=%s hours=%s",
            issue.pk if issue else "?",
            hours,
        )
        return "clamped" if clamped else "created"

    with transaction.atomic():
        est, created = WorkloadEstimate.objects.update_or_create(
            issue=issue,
            defaults={
                "workspace": issue.workspace,
                "project": issue.project,
                "hours": hours,
                "created_by": user_cache.bot_user,
            },
        )
        _record_upsert(
            run,
            "task",
            str(task_id),
            "WorkloadEstimate",
            str(est.id),
            MigrationRecord.STATUS_CREATED if created else MigrationRecord.STATUS_UPDATED,
        )

    return "clamped" if clamped else ("created" if created else "updated")
