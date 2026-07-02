# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Parent-issue rollup (estimates, due date, hours-weighted progress) computed
# on read from a recursive descendants CTE. No core-model edits, no signals —
# see docs/FORK.md "compute-on-read" rationale in the plan brainstorm report.
#
# "Countable issue" is the ONE predicate shared by: this CTE, the matrix
# leaf-exclude (service.py._base_queryset), and the PUT-block / is_parent
# checks (views.py). It is defined here ONCE — countable_issue_q() for ORM
# callers, and mirrored as a raw-SQL fragment inside compute_rollups() for
# the recursive CTE (a Django Q cannot be embedded in raw SQL). P3 carries a
# drift-guard test asserting the two stay in sync.
#
# Table/column names are interpolated from Django model _meta (never string
# literals) so an upstream rename fails loudly at import time, not silently
# at query time — see the module-level _sql_identifiers() call below.

from collections import defaultdict

from django.db import connection
from django.db.models import Exists, OuterRef, Q

from plane.db.models import Issue, State
from plane.db.models.state import StateGroup

from .aggregation import from_cents, to_cents
from .models import WorkloadEstimate
from .service import resolve_guest_scope, resolve_project_scope

MAX_DEPTH = 10
ROW_GUARD = 10_000

NON_COUNTABLE_GROUPS = (StateGroup.CANCELLED.value, StateGroup.TRIAGE.value)


class RollupTooLarge(Exception):
    """Raised when a rollup traversal would exceed ROW_GUARD descendant rows
    across the requested roots (defensive — depth cap alone guarantees
    termination, this bounds pathological fan-out)."""


def countable_issue_q(prefix=""):
    """The countable-issue predicate as a Django Q, for ORM callers.

    `prefix` lets callers apply it through a relation (e.g. "issue" when
    filtering a WorkloadEstimate queryset). Null-state issues are countable
    (state is OPTIONAL on Issue) — expressed as an explicit OR so Django is
    forced to LEFT JOIN state rather than silently dropping NULLs via a
    negated IN on an INNER JOIN.
    """
    p = f"{prefix}__" if prefix else ""
    return (
        Q(**{f"{p}deleted_at__isnull": True})
        & Q(**{f"{p}archived_at__isnull": True})
        & Q(**{f"{p}is_draft": False})
        & (
            Q(**{f"{p}state__isnull": True})
            | ~Q(**{f"{p}state__group__in": NON_COUNTABLE_GROUPS})
        )
    )


def has_countable_children(outer_ref_field):
    """Correlated Exists() subquery: TRUE when Issue has >=1 countable row
    whose parent_id equals the outer queryset's `outer_ref_field`.

    Reused by:
      - service.py._base_queryset (matrix leaf-exclude, outer_ref_field="issue_id")
      - parent_issue_ids() below (outer_ref_field="pk")
    """
    children = Issue.objects.filter(parent_id=OuterRef(outer_ref_field)).filter(
        countable_issue_q()
    )
    return Exists(children)


def is_parent(issue_id) -> bool:
    """Single-issue convenience check — PUT block + single-GET is_parent flag."""
    return Issue.objects.filter(parent_id=issue_id).filter(countable_issue_q()).exists()


def parent_issue_ids(issue_ids):
    """Subset of `issue_ids` that ARE parents (>=1 countable child). One
    annotated query — avoids an is_parent() call per id (bulk endpoint)."""
    if not issue_ids:
        return set()
    return set(
        Issue.objects.filter(id__in=issue_ids)
        .annotate(_has_countable_child=has_countable_children("pk"))
        .filter(_has_countable_child=True)
        .values_list("id", flat=True)
    )


def _sql_identifiers():
    """Column/table names sourced from Django _meta — never string literals
    (rebase safety: an upstream rename fails at import, not at query time)."""
    issue_meta = Issue._meta
    state_meta = State._meta
    return {
        "issue_table": issue_meta.db_table,
        "issue_pk": issue_meta.pk.column,
        "parent_col": issue_meta.get_field("parent").column,
        "project_col": issue_meta.get_field("project").column,
        "target_date_col": issue_meta.get_field("target_date").column,
        "deleted_at_col": issue_meta.get_field("deleted_at").column,
        "archived_at_col": issue_meta.get_field("archived_at").column,
        "is_draft_col": issue_meta.get_field("is_draft").column,
        "state_fk_col": issue_meta.get_field("state").column,
        "state_table": state_meta.db_table,
        "state_pk": state_meta.pk.column,
        "state_group_col": state_meta.get_field("group").column,
    }


def _build_cte_sql(cols):
    # Raw-SQL mirror of countable_issue_q(): NOT deleted, NOT archived, NOT
    # draft, COALESCE(state.group,'') NOT IN ('cancelled','triage') — applied
    # to every RECURSIVE row (descendants), never to the anchor (root) row:
    # the root's own countability is irrelevant to whether ITS children
    # count (is_parent is a property of the root, not a filter on it).
    # A non-countable node prunes its whole subtree (the join can't reach
    # rows the CTE never emitted).
    #
    # Access (project scope) IS applied to the anchor too — an inaccessible
    # root must be OMITTED from the result entirely (see _fold_rollups).
    return f"""
        WITH RECURSIVE rollup_tree AS (
            SELECT
                i."{cols['issue_pk']}" AS root_id,
                i."{cols['issue_pk']}" AS issue_id,
                i."{cols['parent_col']}" AS parent_id,
                0 AS depth
            FROM "{cols['issue_table']}" i
            WHERE i."{cols['issue_pk']}" = ANY(%s)
              AND (
                    i."{cols['project_col']}" = ANY(%s)
                    OR (i."{cols['project_col']}" = ANY(%s) AND i."{cols['issue_pk']}" = ANY(%s))
                  )

            UNION ALL

            SELECT
                t.root_id AS root_id,
                c."{cols['issue_pk']}" AS issue_id,
                c."{cols['parent_col']}" AS parent_id,
                t.depth + 1 AS depth
            FROM "{cols['issue_table']}" c
            JOIN rollup_tree t ON c."{cols['parent_col']}" = t.issue_id
            LEFT JOIN "{cols['state_table']}" s ON s."{cols['state_pk']}" = c."{cols['state_fk_col']}"
            WHERE t.depth < %s
              AND c."{cols['deleted_at_col']}" IS NULL
              AND c."{cols['archived_at_col']}" IS NULL
              AND c."{cols['is_draft_col']}" = FALSE
              AND COALESCE(s."{cols['state_group_col']}", '') NOT IN ('cancelled', 'triage')
              AND (
                    c."{cols['project_col']}" = ANY(%s)
                    OR (c."{cols['project_col']}" = ANY(%s) AND c."{cols['issue_pk']}" = ANY(%s))
                  )
        )
        SELECT
            rt.root_id,
            rt.issue_id,
            rt.parent_id,
            rt.depth,
            i."{cols['target_date_col']}" AS target_date,
            s."{cols['state_group_col']}" AS state_group
        FROM rollup_tree rt
        JOIN "{cols['issue_table']}" i ON i."{cols['issue_pk']}" = rt.issue_id
        LEFT JOIN "{cols['state_table']}" s ON s."{cols['state_pk']}" = i."{cols['state_fk_col']}"
        LIMIT %s
    """


def compute_rollups(user, slug, issue_ids):
    """Return {str(issue_id): rollup_dict} for every requested id the caller
    may access. Ids outside the caller's project scope (or, for a flag-off
    guest, not the guest's own issue) are OMITTED from the result entirely —
    NOT returned with a zero rollup (see docs: "a parent not assigned to a
    restricted guest is omitted entirely").

    rollup_dict = {
        "hours": float,        # sum of countable LEAF estimates (hours > 0)
        "done_hours": float,   # subset of the above where state.group == 'completed'
        "percent": float|None, # round(done/hours, 4), or None when hours == 0
        "due_date": str|None,  # ISO date — max target_date over ALL countable
                                # descendants (leaves AND intermediate nodes)
        "leaf_count": int,     # count of countable leaves with hours > 0
    }

    Callers that need "is this a parent at all" must check separately via
    is_parent() / parent_issue_ids() BEFORE calling this — compute_rollups
    itself does not filter out non-parent roots (an accessible root with zero
    countable children legitimately returns a zero rollup, not an omission).
    """
    root_ids = list({rid for rid in issue_ids})
    if not root_ids:
        return {}

    scope = resolve_project_scope(user, slug, requested_ids=None)
    if not scope:
        return {}

    full_project_ids, restricted_project_ids, own_issue_ids = resolve_guest_scope(
        user, slug, scope
    )
    full_list = list(full_project_ids)
    restricted_list = list(restricted_project_ids)
    own_list = list(own_issue_ids)

    sql = _build_cte_sql(_sql_identifiers())
    params = [
        root_ids, full_list, restricted_list, own_list,  # anchor scope gate
        MAX_DEPTH,
        full_list, restricted_list, own_list,  # recursive-step scope gate
        ROW_GUARD + 1,
    ]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    if len(rows) > ROW_GUARD:
        raise RollupTooLarge()

    return _fold_rollups(root_ids, rows)


def _fold_rollups(root_ids, rows):
    """Fold raw CTE rows (root_id, issue_id, parent_id, depth, target_date,
    state_group) into the per-root rollup dict. Pure/stdlib — no DB calls
    except the one leaf-estimates query below."""
    accessible_roots = set()
    by_root = defaultdict(list)  # root_id -> [(issue_id, parent_id, target_date, state_group), ...] depth>=1 only
    child_keys = set()  # (root_id, parent_id) pairs that have >=1 descendant child
    state_group_by_issue = {}

    for root_id, issue_id, parent_id, depth, target_date, state_group in rows:
        if depth == 0:
            accessible_roots.add(root_id)
            continue
        by_root[root_id].append((issue_id, parent_id, target_date, state_group))
        state_group_by_issue[issue_id] = state_group
        if parent_id is not None:
            child_keys.add((root_id, parent_id))

    leaf_map = defaultdict(list)  # root_id -> [leaf issue_id, ...]
    leaf_issue_ids = set()
    for root_id, entries in by_root.items():
        for issue_id, parent_id, target_date, state_group in entries:
            if (root_id, issue_id) not in child_keys:
                leaf_map[root_id].append(issue_id)
                leaf_issue_ids.add(issue_id)

    hours_cents_by_issue = {}
    if leaf_issue_ids:
        est_rows = WorkloadEstimate.objects.filter(
            issue_id__in=leaf_issue_ids, hours__gt=0
        ).values_list("issue_id", "hours")
        for issue_id, hours in est_rows:
            hours_cents_by_issue[issue_id] = to_cents(hours)

    result = {}
    for root_id in root_ids:
        if root_id not in accessible_roots:
            continue  # not in scope — omitted entirely, not a zero rollup

        entries = by_root.get(root_id, [])
        due_date = None
        for issue_id, parent_id, target_date, state_group in entries:
            if target_date is not None and (due_date is None or target_date > due_date):
                due_date = target_date

        hours_cents = 0
        done_cents = 0
        leaf_count = 0
        for issue_id in leaf_map.get(root_id, []):
            cents = hours_cents_by_issue.get(issue_id)
            if not cents:  # no estimate row, or hours <= 0 (filtered upstream anyway)
                continue
            hours_cents += cents
            leaf_count += 1
            if state_group_by_issue.get(issue_id) == StateGroup.COMPLETED.value:
                done_cents += cents

        result[str(root_id)] = {
            "hours": from_cents(hours_cents),
            "done_hours": from_cents(done_cents),
            "percent": round(done_cents / hours_cents, 4) if hours_cents else None,
            "due_date": due_date.isoformat() if due_date else None,
            "leaf_count": leaf_count,
        }
    return result
