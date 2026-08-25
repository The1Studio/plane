# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload ORM orchestration. Resolves project access, owner attribution
# (earliest ACTIVE non-bot assignee), and drives the pure aggregation in
# aggregation.py. No HTTP concerns here (those live in views.py).

from collections import defaultdict

import pytz
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone as dj_timezone

from plane.db.models import (
    Issue,
    IssueAssignee,
    Project,
    ProjectMember,
    Workspace,
    WorkspaceMember,
)
from plane.db.models.state import StateGroup

from .aggregation import (
    capacity_for_period,
    distribute_cents,
    enumerate_periods,
    from_cents,
    quantize_hours,
    spread_estimate,
    to_cents,
)
from .constants import DEFAULT_MAX_DAILY_HOURS, DEFAULT_WEEK_START_DAY, DEFAULT_WORKDAYS
from .models import WorkloadEstimate, WorkloadSettings

ROW_GUARD = 50_000
ADMIN_ROLE = 20
GUEST_ROLE = 5

# Phase 7 — cap on the `tasks` array returned per assignee row
# (phase-7.md "Truncation cap"). A workspace with thousands of estimated
# issues would otherwise return an unbounded per-assignee array.
WORKLOAD_MAX_TASKS_PER_ASSIGNEE = 200

# Terminal state groups. These are NOT excluded from the matrix -- an unselected
# filter must return everything (see `_base_queryset`). The list exists solely so
# the `overdue` flag can skip work that is already finished or abandoned: a
# completed issue past its target date is done, not late.
_TERMINAL_STATE_GROUPS = [StateGroup.COMPLETED.value, StateGroup.CANCELLED.value]
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


def _scope_filter(project_scope, restricted, user, issue_field="issue_id"):
    """Row filter Q: unrestricted projects in full; restricted (flag-off guest)
    projects narrowed to issues the user is assigned to.

    `issue_field` names the column holding the ISSUE key on the queryset this Q
    is applied to. It defaults to `"issue_id"`, which is correct for a
    `WorkloadEstimate` queryset (the estimate table carries its own denormalized
    `issue_id` / `project_id` columns). `_unestimated_queryset` filters `Issue`
    itself, where that key is the primary key, and passes `issue_field="id"`.

    This is a parameter rather than a second function on purpose: the
    flag-off-guest rule (restricted projects narrow to issues the user is
    assigned to) is the kind of access-control logic that must have exactly one
    definition. A copy of it for the Issue path would pass review today and
    diverge the first time either half is touched.
    """
    if not restricted:
        return Q(project_id__in=project_scope)
    full = set(project_scope) - set(restricted)
    own_issue_ids = _materialize_own_issue_ids(user, restricted)
    q = Q(**{"project_id__in": restricted, f"{issue_field}__in": own_issue_ids})
    if full:
        q |= Q(project_id__in=full)
    return q


def _span_intersects_window_q(date_from, date_to, prefix=""):
    """Q matching an issue whose date span touches [date_from, date_to].

    Undated items (`target_date` NULL) match unconditionally — they are not
    really dated at all, and the client draws them as placeholder bars anchored
    at `start_date ?? today`, inside the window by construction.

    `start_date` is optional even when `target_date` is set, so the span's start
    is `start_date` when present and the target day itself otherwise — the SAME
    rule `packTasksIntoLanes` applies client-side (`start_date ?? target_date`).
    A predicate that read `start_date` alone would compare NULL and silently
    drop every start-less item.

    `prefix` addresses the dates through a relation ("issue__"), which is what
    lets `zero_estimate_count` apply the identical window to `WorkloadEstimate`
    rows. Both meta counters must describe the SAME window or the documented
    "issues_unestimated is a superset of zero_estimate_count" relation stops
    holding — a filtered superset over an unfiltered subset is not a superset.
    """
    start = f"{prefix}start_date"
    target = f"{prefix}target_date"
    span_start_within = Q(**{f"{start}__isnull": False, f"{start}__lte": date_to}) | Q(
        **{f"{start}__isnull": True, f"{target}__lte": date_to}
    )
    return Q(**{f"{target}__isnull": True}) | (
        Q(**{f"{target}__gte": date_from}) & span_start_within
    )


def _unestimated_queryset(slug, scope_q_issue, state_groups, date_from, date_to):
    """Countable, leaf-only issues in scope carrying NO usable estimate.

    "No usable estimate" means no `WorkloadEstimate` row at all, OR one whose
    `hours <= 0` — the same two cases `_base_queryset`'s `hours__gt=0` filter
    drops. The two querysets are exact complements over the countable leaf set,
    which is what lets a task row carry `unestimated` as a plain boolean.

    Unlike `_base_queryset` this starts from `Issue`, because an issue with no
    estimate row has nothing on the estimate table to start from — that absence
    IS the reason these items were invisible on the timeline until now.

    DATED rows ARE window-filtered; undated ones are not. The distinction is the
    whole point. An unestimated item produces no buckets, so the estimated
    path's BUCKET-based "did this contribute to the window" test would drop
    every one of them — but a plain SPAN-intersects-window test on the dates
    themselves works fine, and the two are not the same test. An item with no
    `target_date` is exempt because it is not really dated at all: the client
    draws it as a placeholder bar anchored at `start_date ?? today`, which is
    inside the window by construction.

    This filter was missing until 2026-08-25 and cost more than blank rows.
    Measured on the busiest DEVOPS swimlane: the `Unassigned` row carried 200
    unestimated items, ALL of them dated before `date_from`, which packed into
    66 lanes in which not one bar could ever be visible. Worse, `_task_sort_key`
    sorts unestimated first into the shared 200-task cap, so those 200 stale
    items consumed the entire budget and truncated the in-window work they were
    hiding — a starved cap presenting as an empty board.

    Cost (measured 2026-08-25 against the busiest production workspace, 9,438
    countable leaves): 3,724 rows in 23.4 ms, versus 19.1 ms for 5,714 rows on
    the estimated path. Both anti-joins below resolve to index scans
    (`workload_estimates_issue_id_key`, `issue_parent_id_ce8d76ba`) with no
    sequential scan over `issues`, so this needs no new index — which matters
    beyond performance: `Issue` is a CORE model and `docs/FORK.md` forbids
    editing `db/migrations/`, so an index requirement here would have been a
    redesign, not a migration.
    """
    # Deferred import for the same circular-import reason as `_base_queryset`.
    from .rollup import countable_issue_q, has_countable_children

    qs = (
        Issue.objects.filter(scope_q_issue, workspace__slug=slug)
        # `countable_issue_q()` rather than a hand-written filter: it expresses
        # the null-state case as an explicit OR, which forces Django to LEFT
        # JOIN `state`. A negated `IN` on an INNER JOIN silently drops issues
        # with no state at all (state is OPTIONAL on Issue).
        .filter(countable_issue_q())
        .exclude(state__group=StateGroup.TRIAGE.value)
        # Leaf-only, the SAME rule `_base_queryset` applies. Without it a parent
        # whose children carry the estimates would render as an unestimated
        # dashed bar, contradicting the rollup its own sidebar shows.
        .filter(~has_countable_children("pk"))
        # An `Exists` anti-join, never `.exclude(id__in=<est ids>)`: that id list
        # can hold up to ROW_GUARD entries, and handing it to the database as a
        # literal IN is a different failure mode at scale.
        .filter(
            ~Exists(
                WorkloadEstimate.objects.filter(
                    issue_id=OuterRef("pk"),
                    workspace__slug=slug,
                    hours__gt=0,
                )
            )
        )
    )
    qs = qs.filter(_span_intersects_window_q(date_from, date_to))
    if state_groups:
        qs = qs.filter(state__group__in=state_groups)
    # No `else`, for the reason spelled out at the bottom of `_base_queryset`:
    # no state filter selected means EVERY state group, not a hidden exclusion
    # the user can neither see nor clear.
    return qs


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
    # No `else`: with no state filter selected, EVERY state group is returned,
    # including completed and cancelled. A previous version silently excluded
    # those two, so a workspace whose work was finished rendered an empty matrix
    # while the toolbar showed all five chips unselected -- i.e. the UI claimed
    # "no filter" while the server applied one the user could neither see nor
    # clear. Triage is still excluded above; those are not work items yet.
    return qs


def _resolve_owners(issue_ids):
    """Map issue_id -> [(assignee_id, display_name), ...] for EVERY ACTIVE,
    non-bot assignee, ordered earliest-assigned first. Issues with no
    qualifying assignee are absent (→ Unassigned).

    One query: filter out bots + soft-deleted, require an active ProjectMember
    for the issue's project, order ASC.

    Plane mirrors ClickUp in allowing several assignees on one work item, so an
    issue legitimately has more than one owner. The caller must therefore SPLIT
    each issue's hours across this list rather than adding the full estimate to
    every owner — a raw M2M join would multi-count a shared issue's hours once
    per assignee and inflate the matrix. `compute_workload` does that split with
    `distribute_cents`, so the per-owner shares re-sum to the issue's estimate
    exactly.

    This deliberately no longer collapses to the earliest assignee alone: doing
    so credited a shared task entirely to one person and left every other
    assignee's contribution invisible in the matrix.
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
    owners = defaultdict(list)
    for issue_id, assignee_id, name in rows:
        owners[issue_id].append((assignee_id, name))
    return dict(owners)


def _scope_member_ids(scope, restricted, user):
    """member_id -> display_name for everyone who COULD carry work in scope.

    The companion to `_resolve_owners`, and deliberately built on the SAME
    predicate — an active `ProjectMember`, non-bot. That function answers "who
    owns the work that exists"; this one answers "who could have owned work at
    all", and the two must agree. If they ever drift, a member can hold a bar
    the board refuses to give a row to, or hold a row no assignment can reach.

    Deliberately NOT `WorkspaceMember`: a member of the workspace with no
    project in scope cannot be assigned anything this request returns, so a row
    for them would be a lane nothing could ever fill.

    GUEST RESTRICTION. A flag-off guest may see only their OWN issues in a
    restricted project (`_guest_restricted_projects`), so that project's member
    roster is exactly what the flag exists to withhold — listing it here would
    leak through the workload view a set of names the issue views refuse to
    show. Restricted projects therefore contribute no members EXCEPT the
    requesting user themselves, which leaks nothing they do not already know
    and keeps their own capacity row visible.
    """
    visible = set(scope) - set(restricted)
    members = {}
    if visible:
        members.update(
            ProjectMember.objects.filter(
                project_id__in=visible,
                is_active=True,
                member__is_bot=False,
            ).values_list("member_id", "member__display_name")
        )
    if restricted:
        own = (
            ProjectMember.objects.filter(
                member=user,
                project_id__in=restricted,
                is_active=True,
                member__is_bot=False,
            )
            .values_list("member_id", "member__display_name")
            .first()
        )
        if own:
            members.setdefault(own[0], own[1])
    return members


def _resolve_work_settings(slug):
    """Read this workspace's WorkloadSettings ONCE per request (never per
    row — every row shares the same effective capacity/workday config).
    Falls back to the constants.py defaults when the workspace has no row
    yet (mirrors views.settings_get: a GET never writes on read).

    Returns (max_daily_hours, workdays, week_start_day).
    """
    obj = WorkloadSettings.objects.filter(workspace__slug=slug).first()
    if obj is None:
        return DEFAULT_MAX_DAILY_HOURS, list(DEFAULT_WORKDAYS), DEFAULT_WEEK_START_DAY
    return obj.max_daily_hours, obj.workdays, obj.week_start_day


def _resolve_today(slug):
    """Resolve "today" in the WORKSPACE's timezone, read ONCE per request
    (same pattern as `_resolve_work_settings` — never re-derived per row).

    Phase 7 needed to confirm whether a workspace-level timezone equivalent
    to `Project.timezone` exists before falling back to the project's own
    value. It does: core's `Workspace` model (apps/api/plane/db/models/
    workspace.py) already carries a workspace-level `timezone` CharField
    (same `pytz.common_timezones` choice set as `Project.timezone`), so this
    reads THAT field directly — no project-level fallback, and no new
    workspace-timezone column was added (docs/FORK.md forbids new columns on
    core models; none was needed here since the column already existed).

    Falls back to UTC only defensively — a missing workspace row or an
    unrecognised stored timezone string should not happen for a slug the
    view has already resolved, but a task must never become overdue (or not)
    because of a lookup failure here rather than a real date comparison.
    """
    tz_name = Workspace.objects.filter(slug=slug).values_list("timezone", flat=True).first()
    try:
        tz = pytz.timezone(tz_name) if tz_name else pytz.utc
    except pytz.UnknownTimeZoneError:
        tz = pytz.utc
    return dj_timezone.now().astimezone(tz).date()


def _task_sort_key(task):
    """Ordering for the truncation cap (phase-7.md "Truncation cap").

    UNESTIMATED FIRST, then by `start_date`, then by `target_date`, with null
    dates last on each date key.

    The date half is unchanged and its original reasoning still holds within a
    group: an undated row is the kind a 200-task cap should drop before dated
    work. The unestimated term now sits ABOVE it, which inverts that for one
    case on purpose — an item nobody has estimated is the row most worth
    surfacing, so it survives truncation ahead of estimated work and takes the
    placeholder-lane slots first.

    That is a real trade, not a free win: on a swimlane past the cap this now
    truncates ESTIMATED work that used to fit. `tasks_truncated` still tells
    the client it happened, and `test_sorted_first_and_shares_cap` pins the
    interaction so it stays visible in the suite rather than being discovered
    on a busy swimlane.
    """
    start = task["start_date"]
    target = task["target_date"]
    # `not unestimated` -> False (0) sorts ahead of True (1).
    return (
        not task["unestimated"],
        start is None,
        start or "",
        target is None,
        target or "",
    )


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

    # Read once per request — every row below shares this same effective
    # capacity/workday config (_resolve_capacities / per-row settings reads
    # are gone; D1).
    max_daily_hours, workdays, week_start_day = _resolve_work_settings(slug)

    # Read once per request — every task row's `overdue` flag below shares
    # this same workspace-local "today" (never re-derived per row; see
    # `_resolve_today`'s docstring for the timezone-field confirmation).
    today = _resolve_today(slug)

    # Flag-off guests see only their own assigned workload (core parity).
    restricted = _guest_restricted_projects(user, slug, scope)
    scope_q = _scope_filter(scope, restricted, user)

    qs = _base_queryset(slug, scope_q, state_groups)
    # Same scope rule, applied to `Issue` instead of `WorkloadEstimate` — see
    # `_scope_filter`'s `issue_field` docstring for why this is a parameter and
    # not a second copy of the guest rule.
    scope_q_issue = _scope_filter(scope, restricted, user, issue_field="id")
    unest_qs = _unestimated_queryset(slug, scope_q_issue, state_groups, date_from, date_to)

    # Row guard — bound memory regardless of how the request was narrowed
    # (an admin with an explicit large project list can still blow past it).
    # ONE budget across BOTH querysets, not one ceiling each: a request is
    # refused on the total rows it would load, which is what memory tracks.
    if qs.count() + unest_qs.count() > ROW_GUARD:
        raise WorkloadTooLarge()

    # Per-issue detail (name/identifier/state) is pulled in the SAME query as
    # the aggregation already runs — no second, per-issue fetch (phase-7.md
    # "No N+1"). `issue__project__identifier` and `issue__state__group`
    # traverse via SQL JOIN, not a Python-side loop.
    #
    # `issue__state__name` / `issue__state__color` ride the SAME `state` JOIN
    # `issue__state__group` already forces, so they add columns but no query —
    # `test_task_detail_columns_add_no_extra_queries_per_issue` is the gate
    # that proves it, not this comment. They exist so the timeline can paint a
    # bar with its state's own colour without the client resolving state per
    # project: the workload route is workspace-scoped and routinely mixes
    # projects in one swimlane, and nothing there fetches project states.
    est_rows = list(
        qs.values_list(
            "issue_id",
            "hours",
            "issue__start_date",
            "issue__target_date",
            "issue__name",
            "issue__sequence_id",
            "issue__project_id",
            "issue__project__identifier",
            "issue__state__group",
            "issue__state__name",
            "issue__state__color",
        )
    )
    # Same column list as `est_rows` minus `hours` — there is no estimate to
    # select. Field names lose the `issue__` prefix because this queryset IS
    # `Issue`; the ORDER matches `est_rows` so the two unpack blocks below read
    # as the same shape.
    unest_rows = list(
        unest_qs.values_list(
            "id",
            "start_date",
            "target_date",
            "name",
            "sequence_id",
            "project_id",
            "project__identifier",
            "state__group",
            "state__name",
            "state__color",
        )
    )
    zero_estimate_count = (
        WorkloadEstimate.objects.filter(
            scope_q,
            workspace__slug=slug,
            hours__lte=0,
            issue__deleted_at__isnull=True,
            issue__archived_at__isnull=True,
            issue__is_draft=False,
        )
        # Same window as `_unestimated_queryset`, addressed through the issue
        # relation — see `_span_intersects_window_q` for why the two counters
        # cannot be allowed to disagree about which window they describe.
        .filter(_span_intersects_window_q(date_from, date_to, prefix="issue__"))
        .count()
    )

    # ONE `_resolve_owners` call covering BOTH id sets — it is a single query,
    # and calling it twice would make it two for no benefit.
    issue_ids = [r[0] for r in est_rows]
    owners = _resolve_owners(issue_ids + [r[0] for r in unest_rows])
    assignee_filter = set(assignee_ids) if assignee_ids else None

    buckets = defaultdict(lambda: defaultdict(int))  # owner_id -> period -> cents
    # owner_id -> "YYYY-MM" -> cents (plan D6) — calendar-month accumulation,
    # independent of `granularity`, so the month/quarter badge is exact even
    # when a `week` bucket straddles a month boundary. See spread_estimate's
    # docstring for why this can legitimately disagree with `buckets`.
    month_buckets = defaultdict(lambda: defaultdict(int))
    unscheduled = defaultdict(int)  # owner_id -> cents
    tasks_by_owner = defaultdict(list)  # owner_id -> [task row, ...]
    names = {}
    meta = {
        "issues_counted": 0,
        "issues_unscheduled": 0,
        # Countable in-scope items with no usable estimate. A SUPERSET of
        # `zero_estimate_count`: that counts stored rows with `hours <= 0`,
        # this counts those PLUS items with no estimate row at all. The two
        # deliberately overlap. Counted per ISSUE, never per owner.
        "issues_unestimated": 0,
        "dirty_date_count": 0,
        "zero_estimate_count": zero_estimate_count,
        "truncated": False,
    }

    for (
        issue_id,
        hours,
        start,
        target,
        issue_name,
        sequence_id,
        project_id,
        project_identifier,
        state_group,
        state_name,
        state_color,
    ) in est_rows:
        # An issue may carry SEVERAL assignees (ClickUp parity). Its hours are
        # split evenly across them, so two people sharing an 8h task each carry
        # 4h — never 8h apiece, which would double-count the work, and never 8h
        # to one of them, which would hide the other's load entirely.
        issue_owners = owners.get(issue_id) or [(None, "Unassigned")]
        n_owners = len(issue_owners)

        # Apply the assignee filter to the OWNERS, not to the issue: the split
        # is always computed over the full owner list, so filtering the matrix
        # down to one person shows that person's SHARE (4h), not the whole
        # estimate they happen to co-own.
        visible = [
            (idx, oid, oname)
            for idx, (oid, oname) in enumerate(issue_owners)
            if assignee_filter is None or oid in assignee_filter
        ]
        if not visible:
            continue

        b, mb, uns_cents, dirty = spread_estimate(
            hours, start, target, date_from, date_to, granularity, workdays, week_start_day
        )
        meta["issues_counted"] += 1
        if dirty:
            meta["dirty_date_count"] += 1
        if target is None:
            meta["issues_unscheduled"] += 1

        # Split with the SAME largest-remainder rule the day-spread uses, per
        # bucket and on the whole-issue estimate alike, so every owner's shares
        # re-sum to the issue's own total exactly — an odd cent is handed to the
        # earliest assignee rather than rounded away. Splitting each bucket
        # (not each owner's total) keeps the per-period columns exact too.
        bucket_shares = {k: distribute_cents(c, n_owners) for k, c in b.items()}
        # `month_buckets` is a SECOND partition of the same cents (by calendar
        # month rather than by the requested granularity), so it gets the same
        # per-key split. Note the two partitions are split INDEPENDENTLY, so for
        # a shared issue one owner's month total can differ from their bucket
        # total by the odd cent that largest-remainder hands to the earliest
        # assignee in each partition — bounded by one cent per key and therefore
        # far below the 0.1h the badge actually renders. Splitting per key (not
        # per owner total) is what keeps each month column itself exact.
        month_shares = {k: distribute_cents(c, n_owners) for k, c in mb.items()}
        uns_shares = distribute_cents(uns_cents, n_owners) if uns_cents else None
        est_shares = distribute_cents(to_cents(hours), n_owners)

        for idx, owner_id, owner_name in visible:
            names[owner_id] = owner_name
            for k, parts in bucket_shares.items():
                buckets[owner_id][k] += parts[idx]
            for k, parts in month_shares.items():
                month_buckets[owner_id][k] += parts[idx]
            if uns_shares:
                unscheduled[owner_id] += uns_shares[idx]


        # A task appears in `tasks` iff it has a visible representation in
        # THIS request's window: either it contributed at least one bucket
        # (`b` non-empty — may be a clipped slice of a longer span), or it is
        # explicitly unscheduled (`target is None`, which `spread_estimate`
        # always routes to the Unscheduled bucket regardless of window).
        # An issue whose whole [start, target] span falls entirely outside
        # [date_from, date_to] produces `b == {}` with a non-None target
        # (spread_estimate's documented "span outside window" case) and is
        # deliberately EXCLUDED here — Phase 8's timeline has no window to
        # plot it in, and counting it would burn the truncation cap on rows
        # invisible to the current request.
        if b or target is None:
            for idx, owner_id, _ in visible:
                tasks_by_owner[owner_id].append(
                    {
                        "id": str(issue_id),
                        "project_id": str(project_id),
                        "identifier": f"{project_identifier}-{sequence_id}",
                        "name": issue_name,
                        # THIS OWNER'S SHARE of the whole issue estimate — not
                        # the windowed slice `b` sums to (see the docstring on
                        # the `tasks` assembly below for why those two
                        # deliberately do not reconcile), and not the issue
                        # total when the issue is shared. A row's `hours` must
                        # be what that person carries, or the task list would
                        # contradict the buckets above it. `total_hours` keeps
                        # the undivided estimate available for display.
                        "hours": from_cents(est_shares[idx]),
                        "total_hours": quantize_hours(hours),
                        "assignee_count": n_owners,
                        "start_date": start.isoformat() if start else None,
                        "target_date": target.isoformat() if target else None,
                        "state_group": state_group,
                        # Normalised to "" rather than left as None so the
                        # client's fallback has ONE empty shape to test, not
                        # two. `State.color` is a free CharField, not a
                        # validated hex — the client treats it as an opaque
                        # CSS colour string and never parses it.
                        "state_name": state_name or "",
                        "state_color": state_color or "",
                        # ALWAYS emitted, never omitted. The client must not
                        # have to infer this from `hours == 0`: a stored
                        # zero-hour estimate makes that test ambiguous, which
                        # is the whole reason the flag exists. Absent is not
                        # false — a missing key reads as falsy and would work
                        # by accident until a consumer used `in` or a strict
                        # schema.
                        "unestimated": False,
                        "overdue": bool(
                            target is not None
                            and target < today
                            and state_group not in _TERMINAL_STATE_GROUPS
                        ),
                    }
                )

    # Unestimated items — the same owner split and assignee filter as above,
    # but no hours to spread anywhere. They write NOTHING to `buckets`,
    # `month_buckets` or `unscheduled`, so every capacity figure in the
    # response is byte-identical to what it would be without them; the only
    # thing they add is a task row for the timeline to draw a placeholder from.
    for (
        issue_id,
        start,
        target,
        issue_name,
        sequence_id,
        project_id,
        project_identifier,
        state_group,
        state_name,
        state_color,
    ) in unest_rows:
        issue_owners = owners.get(issue_id) or [(None, "Unassigned")]
        n_owners = len(issue_owners)
        visible = [
            (oid, oname)
            for oid, oname in issue_owners
            if assignee_filter is None or oid in assignee_filter
        ]
        if not visible:
            continue

        # Counted once per ISSUE, before the per-owner fan-out below — a
        # two-assignee item is one unestimated work item, not two.
        meta["issues_unestimated"] += 1

        # The window filter lives in `_unestimated_queryset`, not here, so the
        # ROW_GUARD count and the 200-task cap below both see the filtered set.
        # Applying it in this loop instead would leave the cap being spent on
        # rows that are about to be discarded — which is the exact failure the
        # filter was added to end. Undated items reach this point on purpose;
        # the client draws them as placeholder bars.
        for owner_id, owner_name in visible:
            names[owner_id] = owner_name
            tasks_by_owner[owner_id].append(
                {
                    "id": str(issue_id),
                    "project_id": str(project_id),
                    "identifier": f"{project_identifier}-{sequence_id}",
                    "name": issue_name,
                    # Zero, not null: `hours` is a number everywhere else and a
                    # client summing the array must not have to guard for None.
                    # `unestimated` is what carries "there is no estimate".
                    "hours": 0.0,
                    "total_hours": 0.0,
                    # The real owner count, exactly as on an estimated row —
                    # nothing about sharing changes because the estimate is
                    # missing.
                    "assignee_count": n_owners,
                    "start_date": start.isoformat() if start else None,
                    "target_date": target.isoformat() if target else None,
                    "state_group": state_group,
                    "state_name": state_name or "",
                    "state_color": state_color or "",
                    "unestimated": True,
                    # Same rule as an estimated row: a non-null target in the
                    # past on a non-terminal item. An undated unestimated item
                    # is therefore never overdue.
                    "overdue": bool(
                        target is not None
                        and target < today
                        and state_group not in _TERMINAL_STATE_GROUPS
                    ),
                }
            )

    period_set = set()
    for pm in buckets.values():
        period_set.update(pm.keys())
    # UNION with every period the window covers, never a replacement. Before
    # this, `periods` held only buckets that received hours, so `capacity_buckets`
    # below priced "the weeks somebody happened to be busy" rather than the
    # requested range — a member's `total`/`total_capacity` badge moved whenever
    # an UNRELATED member scheduled work into a new week. It also left every
    # zero-hour column with no capacity entry and therefore no heat cell.
    # The union direction matters: `spread_estimate` clips hours to the window
    # but keys them off the un-clipped day, so a populated key can legitimately
    # precede the window's first key (see `enumerate_periods`' docstring).
    period_set.update(enumerate_periods(date_from, date_to, granularity, week_start_day))
    periods = sorted(period_set)

    rows = []
    # `month_buckets` is included here too, not just `buckets`/`unscheduled`:
    # `spread_estimate` now clips `month_buckets` to the WHOLE calendar months
    # the window touches, a wider range than [date_from, date_to] itself (see
    # its docstring), so a member whose only estimate falls in that widened
    # slice but outside the window proper can have month-only data with no
    # `buckets` or `unscheduled` entry at all. Dropping them here would silently
    # omit their row from the response even though `month_sparse` below has
    # a real total to show.
    owner_ids = (
        set(buckets.keys())
        | set(unscheduled.keys())
        | set(month_buckets.keys())
        # `tasks_by_owner` is the ONLY one of these an unestimated item writes
        # to. Without it the UNASSIGNED row vanishes whenever the only
        # unassigned work is unestimated: `scope_members` below contributes
        # member ids and never `None`, and `None` reached this set solely
        # through the three hour maps above.
        | set(tasks_by_owner.keys())
    )
    # A member with no ESTIMATED work has no entry in any of the three maps
    # above, so before this union they had no row at all — and the board could
    # answer "who is overloaded" but never "who is free". Two different
    # absences produced that same silence: no assigned work item, and assigned
    # work items nobody estimated. Driving rows off the member list collapses
    # them into one case, which is right, because from the reader's side they
    # were never distinguishable.
    #
    # `names` is fed from the same call and this is load-bearing, not tidiness:
    # `assignee_name` below falls back to "Unassigned" for an id `names` does
    # not know, so a member id reaching `owner_ids` without a name renders as a
    # SECOND row called "Unassigned" — worse than the row being missing.
    #
    # Filtered to `assignee_filter` for the same reason the per-issue owner
    # split is (see its comment above): that filter is applied to OWNERS, never
    # to `owner_ids`, so without this a request narrowed to one person would
    # still carry every other member's empty lane.
    scope_members = _scope_member_ids(scope, restricted, user)
    for member_id, display_name in scope_members.items():
        if assignee_filter is not None and member_id not in assignee_filter:
            continue
        owner_ids.add(member_id)
        names.setdefault(member_id, display_name)
    # Same workspace-wide capacity for every row now (D1) — computed ONCE and
    # referenced by each row below, not rebuilt per-owner. Prorated over
    # every period column in the response (not just a given row's populated
    # buckets) so the matrix can render a capacity reference even for
    # periods with zero hours logged.
    capacity_buckets = {
        period: capacity_for_period(max_daily_hours, period, granularity, workdays)
        for period in periods
    }
    total_capacity = sum(capacity_buckets.values())
    for owner_id in owner_ids:
        pm = buckets.get(owner_id, {})
        sparse = {k: from_cents(c) for k, c in pm.items() if c}
        total = from_cents(sum(pm.values()))

        # Sparse, calendar-month keyed, independent of `granularity` (plan D6).
        # No padding against `periods` — `periods` is granularity-scoped and
        # `month_buckets` deliberately is not.
        month_pm = month_buckets.get(owner_id, {})
        month_sparse = {k: from_cents(c) for k, c in month_pm.items() if c}

        # There is always an effective capacity now (settings row or
        # constants.py default) — every row carries over/total_over flags,
        # not just members who used to have an explicit capacity row (D1).
        over = {
            period: sparse.get(period, 0) > capacity_buckets[period]
            for period in periods
        }
        total_over = total > total_capacity

        # Phase 7 — per-task rows for the timeline (phase-7.md "Response
        # shape"). `hours` on each task is the issue's WHOLE estimate, while
        # `buckets` above stays the windowed, workday-spread distribution.
        # These two DELIBERATELY do not reconcile for an issue whose span is
        # clipped by [date_from, date_to]: a 10h task starting before the
        # window shows `hours: 10.0` (the bar label matches the work item)
        # even though only the in-window slice of it landed in `buckets`. A
        # future reader diffing task hours against summed buckets is not
        # looking at a bug.
        raw_tasks = tasks_by_owner.get(owner_id, [])
        raw_tasks.sort(key=_task_sort_key)
        tasks_truncated = len(raw_tasks) > WORKLOAD_MAX_TASKS_PER_ASSIGNEE
        tasks = raw_tasks[:WORKLOAD_MAX_TASKS_PER_ASSIGNEE]

        rows.append(
            {
                "assignee_id": str(owner_id) if owner_id else None,
                "assignee_name": names.get(owner_id, "Unassigned"),
                "buckets": sparse,
                "month_buckets": month_sparse,
                "total": total,
                "capacity_buckets": capacity_buckets,
                "over": over,
                "total_over": total_over,
                "tasks": tasks,
                "tasks_truncated": tasks_truncated,
            }
        )
    # Rows read alphabetically, not by load. A reader looking for one person
    # scans a name list; ranking by `-total` meant that list re-ordered itself
    # every time an estimate changed, so the same member sat somewhere new on
    # each visit. The unassigned bucket is pinned first, keyed on `assignee_id
    # is None` (False sorts before True) rather than on the display name — a
    # real member literally called "Unassigned" still sorts under U instead of
    # stealing the pinned slot. `casefold`, not `lower`, so non-ASCII display
    # names compare the way the reader expects.
    rows.sort(key=lambda r: (r["assignee_id"] is not None, r["assignee_name"].casefold()))

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
            "issues_unestimated": 0,
            "dirty_date_count": 0,
            "zero_estimate_count": 0,
            "unscheduled_ratio": 0,
            "truncated": False,
        },
    }
