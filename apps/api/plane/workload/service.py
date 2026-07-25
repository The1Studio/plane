# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload ORM orchestration. Resolves project access, owner attribution
# (earliest ACTIVE non-bot assignee), and drives the pure aggregation in
# aggregation.py. No HTTP concerns here (those live in views.py).

from collections import defaultdict

from django.db.models import Exists, OuterRef, Q

from plane.db.models import (
    Issue,
    IssueAssignee,
    Project,
    ProjectMember,
    WorkspaceMember,
)
from plane.db.models.state import StateGroup

from .aggregation import capacity_for_period, from_cents, spread_estimate
from .models import WorkloadCapacity, WorkloadEstimate

ROW_GUARD = 50_000
ADMIN_ROLE = 20
GUEST_ROLE = 5

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


# Guest visibility — mirrors core Plane's issue gate (app/views/issue/base.py):
# a GUEST in a project with guest_view_all_features=False may see only their
# OWN content. Workload is assignee-attributed, so "own" = issues assigned to
# the guest. Workspace admins are never restricted (core admin bypass).


def is_guest_restricted(user, slug, project_id) -> bool:
    """True if `user` is a GUEST in this project AND the project hides team-wide
    data (guest_view_all_features=False). Workspace admins are never restricted."""
    if _is_workspace_admin(user, slug):
        return False
    return ProjectMember.objects.filter(
        member=user,
        workspace__slug=slug,
        project_id=project_id,
        role=GUEST_ROLE,
        is_active=True,
        project__guest_view_all_features=False,
    ).exists()


def is_issue_assignee(user, project_id, issue_id) -> bool:
    """True if `user` is an active (non-deleted) assignee of the issue."""
    return IssueAssignee.objects.filter(
        issue_id=issue_id,
        project_id=project_id,
        assignee_id=user.id,
        deleted_at__isnull=True,
    ).exists()


def _guest_restricted_projects(user, slug, scope):
    """Subset of `scope` where `user` is a flag-off GUEST (own-data only)."""
    if not scope or _is_workspace_admin(user, slug):
        return set()
    return set(
        ProjectMember.objects.filter(
            member=user,
            workspace__slug=slug,
            project_id__in=scope,
            role=GUEST_ROLE,
            is_active=True,
            project__guest_view_all_features=False,
        ).values_list("project_id", flat=True)
    )


def _materialize_own_issue_ids(user, restricted_project_ids):
    """Issue ids the user is an active assignee of, within `restricted_project_ids`.

    MATERIALIZED as a list (not a lazy queryset) — the rollup CTE needs a
    Python list it can pass as a raw-SQL bound parameter (a Django queryset/Q
    cannot be embedded in raw SQL). This is the SSOT for "what a flag-off
    guest owns" — rollup.py must never re-derive this membership rule in SQL.
    """
    if not restricted_project_ids:
        return []
    return list(
        IssueAssignee.objects.filter(
            assignee_id=user.id,
            deleted_at__isnull=True,
            project_id__in=restricted_project_ids,
        ).values_list("issue_id", flat=True)
    )


def resolve_guest_scope(user, slug, scope):
    """Split `scope` into (full_project_ids, restricted_project_ids,
    own_issue_ids) for raw-SQL callers (rollup.py) that cannot embed a Django
    Q in SQL. `own_issue_ids` is materialized (see above). Mirrors the same
    project/guest split `_scope_filter` uses for ORM queries — SSOT for guest
    membership rules stays in this module either way.
    """
    restricted = _guest_restricted_projects(user, slug, scope)
    full = set(scope) - restricted
    own_issue_ids = _materialize_own_issue_ids(user, restricted)
    return full, restricted, own_issue_ids


def _scope_filter(project_scope, restricted, user):
    """Row filter Q: unrestricted projects in full; restricted (flag-off guest)
    projects narrowed to issues the user is assigned to."""
    if not restricted:
        return Q(project_id__in=project_scope)
    full = set(project_scope) - set(restricted)
    own_issue_ids = _materialize_own_issue_ids(user, restricted)
    q = Q(project_id__in=restricted, issue_id__in=own_issue_ids)
    if full:
        q |= Q(project_id__in=full)
    return q


def _base_queryset(slug, scope_q, state_groups):
    # Deferred import — rollup.py imports resolve_project_scope/resolve_guest_scope
    # from THIS module at its top level; importing rollup.py at service.py's own
    # top level would create a circular import. Both modules are fully loaded by
    # the time any request handler runs, so a call-time import is safe here.
    from .rollup import has_countable_children

    qs = (
        WorkloadEstimate.objects.filter(
            scope_q,
            workspace__slug=slug,
            hours__gt=0,
            issue__deleted_at__isnull=True,
            issue__archived_at__isnull=True,
            issue__is_draft=False,
        )
        .exclude(issue__state__group=StateGroup.TRIAGE.value)
        # Leaf-only counting (matrix double-count fix): an estimate whose
        # issue has a countable child is a PARENT estimate — legacy/ignored,
        # never surfaced in the matrix (rollups own parent totals instead).
        .filter(~has_countable_children("issue_id"))
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


def _resolve_capacities(owner_ids, slug):
    """Map member_id -> weekly_hours for workspace-wide (project=None)
    WorkloadCapacity rows in this workspace. Members with no capacity row are
    absent (caller treats as "no capacity set" -> empty capacity_buckets,
    over=False everywhere). Mirrors _resolve_owners' shape.
    """
    owner_ids = {oid for oid in owner_ids if oid is not None}
    if not owner_ids:
        return {}
    rows = WorkloadCapacity.objects.filter(
        workspace__slug=slug, project__isnull=True, member_id__in=owner_ids
    ).values_list("member_id", "weekly_hours")
    return dict(rows)


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

    # Flag-off guests see only their own assigned workload (core parity).
    restricted = _guest_restricted_projects(user, slug, scope)
    scope_q = _scope_filter(scope, restricted, user)

    qs = _base_queryset(slug, scope_q, state_groups)

    # Row guard — bound memory regardless of how the request was narrowed
    # (an admin with an explicit large project list can still blow past it).
    if qs.count() > ROW_GUARD:
        raise WorkloadTooLarge()

    est_rows = list(
        qs.values_list("issue_id", "hours", "issue__start_date", "issue__target_date")
    )
    zero_estimate_count = WorkloadEstimate.objects.filter(
        scope_q,
        workspace__slug=slug,
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
    capacities = _resolve_capacities(owner_ids, slug)
    for owner_id in owner_ids:
        pm = buckets.get(owner_id, {})
        sparse = {k: from_cents(c) for k, c in pm.items() if c}
        total = from_cents(sum(pm.values()))

        weekly_capacity = capacities.get(owner_id)
        if weekly_capacity is not None:
            # Prorated over every period column in the response (not just
            # this row's populated buckets) so the matrix can render a
            # capacity reference even for periods with zero hours logged.
            capacity_buckets = {
                period: capacity_for_period(weekly_capacity, period, granularity)
                for period in periods
            }
            over = {
                period: sparse.get(period, 0) > capacity_buckets[period]
                for period in periods
            }
            total_over = total > sum(capacity_buckets.values())
        else:
            capacity_buckets = {}
            over = {}
            total_over = False

        rows.append(
            {
                "assignee_id": str(owner_id) if owner_id else None,
                "assignee_name": names.get(owner_id, "Unassigned"),
                "buckets": sparse,
                "total": total,
                "capacity_buckets": capacity_buckets,
                "over": over,
                "total_over": total_over,
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


BULK_ESTIMATES_CAP = 500


class BulkEstimatesError(Exception):
    """Raised by bulk_estimates AND validate_bulk_issue_ids for caller-correctable
    input errors (empty or oversize issue_ids list). Caught by the view and
    mapped to HTTP 400.

    Using a dedicated type — NOT bare ValueError — ensures that unexpected
    ValueErrors from deeper ORM/Python code propagate as 500 instead of
    being silently swallowed as a 400 response.
    """


def validate_bulk_issue_ids(issue_ids):
    """Shared cap/empty validation for every bulk `issue_ids` endpoint
    (estimates AND rollups) — SSOT so the two endpoints can't drift on the
    cap value or error wording. Raises BulkEstimatesError; never returns
    a value (callers just call it for its side effect: raise-or-pass)."""
    if not issue_ids:
        raise BulkEstimatesError("issue_ids must not be empty")
    if len(issue_ids) > BULK_ESTIMATES_CAP:
        raise BulkEstimatesError(
            f"Too many issue_ids (max {BULK_ESTIMATES_CAP}, got {len(issue_ids)})"
        )


def bulk_estimates(user, slug, issue_ids):
    """Return {str(issue_id): hours} for all in-scope stored estimates.

    AuthZ reuses the SAME scope primitives as compute_workload — one ORM
    query enforces project membership AND the flag-off guest restriction
    (no per-issue loop, no cross-project leak).

    Returns ALL stored rows including hours == 0 (the grid needs the zero).
    Issues with no row are omitted (caller can treat them as unset). Rows
    whose issue is a PARENT (>=1 countable child) are also omitted — keep-
    but-ignore means ignored everywhere; returning a parent's legacy hours
    here while single-GET nulls it would leak the ignored value into the
    spreadsheet (round-5 plan MAJOR-B.1). A parent now looks like "no
    estimate" here, same as the matrix's leaf-only treatment.

    Raises:
        BulkEstimatesError: on empty or oversize issue_ids list (→ HTTP 400).
        Any other exception propagates uncaught (→ HTTP 500 from DRF handler).
    """
    # Deferred import — see the matching note in _base_queryset (circular
    # import: rollup.py imports resolve_project_scope/resolve_guest_scope
    # from this module at its top level).
    from .rollup import has_countable_children

    validate_bulk_issue_ids(issue_ids)

    scope = resolve_project_scope(user, slug, requested_ids=None, route_project_id=None)
    if not scope:
        return {}

    restricted = _guest_restricted_projects(user, slug, scope)
    scope_q = _scope_filter(scope, restricted, user)

    rows = (
        WorkloadEstimate.objects.filter(
            scope_q,
            workspace__slug=slug,
            issue_id__in=issue_ids,
        )
        .filter(~has_countable_children("issue_id"))
        .values_list("issue_id", "hours")
    )

    return {str(issue_id): hours for issue_id, hours in rows}


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
