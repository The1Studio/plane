# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload ORM orchestration. Resolves project access, owner attribution
# (earliest ACTIVE non-bot assignee), and drives the pure aggregation in
# aggregation.py. No HTTP concerns here (those live in views.py).

from collections import defaultdict

from django.db.models import Exists, OuterRef

from plane.db.models import (
    Issue,
    IssueAssignee,
    Project,
    ProjectMember,
    WorkspaceMember,
)
from plane.db.models.state import StateGroup

from .aggregation import from_cents, spread_estimate
from .models import WorkloadEstimate

ROW_GUARD = 50_000
ADMIN_ROLE = 20

_DEFAULT_EXCLUDED_GROUPS = [StateGroup.COMPLETED.value, StateGroup.CANCELLED.value]
VALID_STATE_GROUPS = {g.value for g in StateGroup}


class WorkloadTooLarge(Exception):
    """Raised when an unfiltered workspace query exceeds ROW_GUARD."""


def _is_workspace_admin(user, slug) -> bool:
    return WorkspaceMember.objects.filter(
        workspace__slug=slug, member=user, role=ADMIN_ROLE, is_active=True
    ).exists()


def _accessible_project_ids(user, slug):
    """Project ids the user is an ACTIVE member of within this workspace."""
    return set(
        ProjectMember.objects.filter(
            member=user, workspace__slug=slug, is_active=True
        ).values_list("project_id", flat=True)
    )


def resolve_project_scope(user, slug, requested_ids, route_project_id=None):
    """The set of project ids the query may read — the CRITICAL access boundary.

    - Workspace admin → all projects in the workspace.
    - Otherwise → projects the user actively belongs to.
    - `requested_ids` (caller filter) is INTERSECTED with the accessible set
      (never trusted outright — prevents cross-project workload leakage).
    - `route_project_id` (project route) further narrows to that one project.
    """
    if _is_workspace_admin(user, slug):
        accessible = set(
            Project.objects.filter(workspace__slug=slug).values_list("id", flat=True)
        )
    else:
        accessible = _accessible_project_ids(user, slug)

    scope = set(accessible)
    if requested_ids:
        scope &= set(requested_ids)
    if route_project_id is not None:
        scope &= {route_project_id}
    return scope


def _base_queryset(slug, project_scope, state_groups):
    qs = (
        WorkloadEstimate.objects.filter(
            workspace__slug=slug,
            hours__gt=0,
            project_id__in=project_scope,
            issue__deleted_at__isnull=True,
            issue__archived_at__isnull=True,
            issue__is_draft=False,
        )
        .exclude(issue__state__group=StateGroup.TRIAGE.value)
    )
    if state_groups:
        qs = qs.filter(issue__state__group__in=state_groups)
    else:
        qs = qs.exclude(issue__state__group__in=_DEFAULT_EXCLUDED_GROUPS)
    return qs


def _resolve_owners(issue_ids):
    """Map issue_id -> (assignee_id, display_name) for the earliest ACTIVE,
    non-bot assignee. Issues with no qualifying assignee are absent (→ Unassigned).

    One query: filter out bots + soft-deleted, require an active ProjectMember
    for the issue's project, order ASC and keep the first per issue. Avoids the
    M2M-join fan-out that would multi-count an issue's hours.
    """
    if not issue_ids:
        return {}
    active_member = ProjectMember.objects.filter(
        project_id=OuterRef("project_id"),
        member_id=OuterRef("assignee_id"),
        is_active=True,
    )
    rows = (
        IssueAssignee.objects.filter(
            issue_id__in=issue_ids,
            deleted_at__isnull=True,
            assignee__is_bot=False,
        )
        .filter(Exists(active_member))
        .order_by("issue_id", "created_at", "assignee_id")
        .values_list("issue_id", "assignee_id", "assignee__display_name")
    )
    owners = {}
    for issue_id, assignee_id, name in rows:
        if issue_id not in owners:  # first = earliest active non-bot
            owners[issue_id] = (assignee_id, name)
    return owners


def compute_workload(
    user,
    slug,
    granularity,
    date_from,
    date_to,
    requested_project_ids=None,
    assignee_ids=None,
    state_groups=None,
    route_project_id=None,
):
    """Return the workload response dict. Inputs are assumed validated by the view."""
    scope = resolve_project_scope(
        user, slug, requested_project_ids, route_project_id=route_project_id
    )
    if not scope:
        return _empty_response(granularity, date_from, date_to)

    qs = _base_queryset(slug, scope, state_groups)

    # Row guard — bound memory regardless of how the request was narrowed
    # (an admin with an explicit large project list can still blow past it).
    if qs.count() > ROW_GUARD:
        raise WorkloadTooLarge()

    est_rows = list(
        qs.values_list("issue_id", "hours", "issue__start_date", "issue__target_date")
    )
    zero_estimate_count = WorkloadEstimate.objects.filter(
        workspace__slug=slug,
        project_id__in=scope,
        hours__lte=0,
        issue__deleted_at__isnull=True,
        issue__archived_at__isnull=True,
        issue__is_draft=False,
    ).count()

    issue_ids = [r[0] for r in est_rows]
    owners = _resolve_owners(issue_ids)
    assignee_filter = set(assignee_ids) if assignee_ids else None

    buckets = defaultdict(lambda: defaultdict(int))  # owner_id -> period -> cents
    unscheduled = defaultdict(int)  # owner_id -> cents
    names = {}
    meta = {
        "issues_counted": 0,
        "issues_unscheduled": 0,
        "dirty_date_count": 0,
        "zero_estimate_count": zero_estimate_count,
        "truncated": False,
    }

    for issue_id, hours, start, target in est_rows:
        owner = owners.get(issue_id)
        owner_id = owner[0] if owner else None
        if assignee_filter is not None and owner_id not in assignee_filter:
            continue
        names[owner_id] = owner[1] if owner else "Unassigned"

        b, uns_cents, dirty = spread_estimate(
            hours, start, target, date_from, date_to, granularity
        )
        meta["issues_counted"] += 1
        if dirty:
            meta["dirty_date_count"] += 1
        if target is None:
            meta["issues_unscheduled"] += 1
        for k, c in b.items():
            buckets[owner_id][k] += c
        if uns_cents:
            unscheduled[owner_id] += uns_cents

    period_set = set()
    for pm in buckets.values():
        period_set.update(pm.keys())
    periods = sorted(period_set)

    rows = []
    owner_ids = set(buckets.keys()) | set(unscheduled.keys())
    for owner_id in owner_ids:
        pm = buckets.get(owner_id, {})
        sparse = {k: from_cents(c) for k, c in pm.items() if c}
        total = from_cents(sum(pm.values()))
        rows.append(
            {
                "assignee_id": str(owner_id) if owner_id else None,
                "assignee_name": names.get(owner_id, "Unassigned"),
                "buckets": sparse,
                "total": total,
            }
        )
    rows.sort(key=lambda r: (-r["total"], r["assignee_name"]))

    unscheduled_list = [
        {"assignee_id": str(oid) if oid else None, "hours": from_cents(c)}
        for oid, c in unscheduled.items()
        if c
    ]

    counted = meta["issues_counted"]
    meta["unscheduled_ratio"] = (
        round(meta["issues_unscheduled"] / counted, 4) if counted else 0
    )

    return {
        "granularity": granularity,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "periods": periods,
        "rows": rows,
        "unscheduled": unscheduled_list,
        "meta": meta,
    }


def _empty_response(granularity, date_from, date_to):
    return {
        "granularity": granularity,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "periods": [],
        "rows": [],
        "unscheduled": [],
        "meta": {
            "issues_counted": 0,
            "issues_unscheduled": 0,
            "dirty_date_count": 0,
            "zero_estimate_count": 0,
            "unscheduled_ratio": 0,
            "truncated": False,
        },
    }
