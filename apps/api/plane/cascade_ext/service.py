# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Cascade logic — level-order BFS descendant collection shared by both the
# preview and apply endpoints (docs/FORK.md touch-point 2, no core view
# edited). Contract, decisions, and test matrix:
# plans/260822-cascade-complete-sub-items/phase-1-cascade-backend.md
# plans/260828-module-cascade-terminal-status/phase-1-module-cascade-backend.md

from __future__ import annotations

import json
import logging
import uuid

from django.db import transaction
from django.utils import timezone

from plane.bgtasks.issue_activities_task import issue_activity
from plane.bgtasks.webhook_task import model_activity
from plane.db.models import Issue, ProjectMember, State
from plane.db.models.state import StateGroup

logger = logging.getLogger(__name__)

# Plan Decision 6 — "All descendants, recursively, with a `visited` set and
# MAX_DEPTH = 20 against `parent` cycles."
MAX_DEPTH = 20

TERMINAL_GROUPS = {StateGroup.COMPLETED.value, StateGroup.CANCELLED.value}

# Bulk-write batch size for the cascaded children (phase file § Implementation).
_BULK_UPDATE_BATCH = 100

# Hard cap on live nodes a single module cascade will write (plan M4). "Live"
# is post-pruning — terminal nodes and everything behind them are gone before
# the count is taken, so the cap measures exactly what a confirm would write.
MAX_MODULE_CASCADE_ITEMS = 100

# Module status -> the `State.group` that status cascades to (plan M7). A
# completed module completes its items; a cancelled module cancels them.
MODULE_STATUS_TO_STATE_GROUP = {
    "completed": StateGroup.COMPLETED.value,
    "cancelled": StateGroup.CANCELLED.value,
}


class CascadeCapExceeded(Exception):
    """Raised when a module cascade would exceed MAX_MODULE_CASCADE_ITEMS.

    The view turns this into a 400 carrying the real live count (`total_live`).
    Raising it BEFORE any transaction opens is what guarantees nothing —
    including the module's own status — is written.
    """

    def __init__(self, total_live):
        super().__init__(
            f"cascade exceeds MAX_MODULE_CASCADE_ITEMS ({MAX_MODULE_CASCADE_ITEMS})"
        )
        self.total_live = total_live


def resolve_target_group(old_state, new_state) -> str | None:
    """Which terminal group (if any) a parent's state change should cascade.

    - `new_state` isn't terminal at all -> None (no cascade; reverse-cascade
      and "leaving a terminal group" are both explicitly out of scope).
    - `new_state` is terminal and `old_state` was already in THAT SAME
      terminal group -> None (Decision 4: a move between two states of the
      same terminal group, e.g. a rename, is a no-op).
    - `new_state` is terminal and differs from `old_state`'s group (entering
      a terminal group fresh, or moving from one terminal group to the
      other) -> that group. Cascade mirrors whichever terminal group the
      parent entered (Decision 4).
    """
    if new_state is None or new_state.group not in TERMINAL_GROUPS:
        return None
    if old_state is not None and old_state.group == new_state.group:
        return None
    return new_state.group


def _has_terminal_ancestor_to_root(*, issue_id, traversed_ids) -> bool:
    """Is a posted-but-rejected id sitting under a pruned terminal branch?

    Phase 0 § 2: after pruning, a live id beneath a terminal node is in
    neither the eligible set nor `traversed_ids`, and `not_a_descendant`
    (or `not_in_module_tree`) would be a FALSE label — the id genuinely is
    a descendant, it is just behind a branch the walk refused to follow.

    This helper walks the id's parent chain (bounded by MAX_DEPTH, the same
    bound as the walk itself) and returns True only when it reaches a
    terminal node the cascade itself ENCOUNTERED (recorded in
    `traversed_ids`) — which is the proof that the branch connects to this
    cascade's root rather than being some unrelated terminal ancestor. A
    chain that ends without one (or a chain that leaves the tree entirely)
    returns False, preserving `not_a_descendant` / `not_in_module_tree` for
    genuinely foreign ids. Runs only for ids that were already going to be
    rejected, so it costs nothing on the normal path.
    """
    traversed_uuids = {uuid.UUID(x) for x in traversed_ids}
    current = issue_id
    for _ in range(MAX_DEPTH):
        row = (
            Issue.issue_objects.filter(pk=current)
            .values("parent_id", "state__group")
            .first()
        )
        if row is None or row["parent_id"] is None:
            # The chain ended inside this cascade's subject (or left the tree).
            return False
        parent_id = row["parent_id"]
        if parent_id in traversed_uuids:
            # Parent is a terminal node this cascade actually encountered.
            return True
        current = parent_id
    return False


def _collect_from_seeds(
    *, seed_ids, include_seeds, target_group, actor_id
) -> dict:
    """Level-order BFS from a SET of seed issue ids.

    Shared by the per-issue cascade (`include_seeds=False` — seeds are the
    roots, excluded from the result) and the module cascade
    (`include_seeds=True` — seeds are themselves candidates at depth 0).

    Returned key names are frozen for the per-issue caller:

        {
          "descendants": [ {id, identifier, name, depth, project_id,
                             project_name, state_id, state_name,
                             state_group, target_state_id, eligible,
                             reason}, ... ],
          "depth_capped": bool,
          "traversed_ids": {str(id), ...}   # every TERMINAL node encountered
                                             # (seeds included when
                                             # include_seeds=True) — pruned
                                             # from the result, never walked.
        }
    """
    visited = set(seed_ids)
    traversed_ids: set[str] = set()
    raw_nodes = []  # [(Issue, depth), ...] — LIVE nodes only, level order
    depth = 0
    depth_capped = False

    if include_seeds:
        # Seeds are fetched with the same soft-delete-aware manager and enter
        # at depth 0. A terminal seed is recorded in `traversed_ids` and its
        # subtree is pruned (plan M8 — a terminal item is a decision about
        # that branch; reaching past it would override it silently).
        for issue in Issue.issue_objects.filter(id__in=seed_ids).select_related(
            "state", "project"
        ):
            if (issue.state.group if issue.state else None) in TERMINAL_GROUPS:
                traversed_ids.add(str(issue.id))
            else:
                raw_nodes.append((issue, 0))
        frontier = [issue.id for issue, _ in raw_nodes]
    else:
        frontier = list(visited)

    while frontier and depth < MAX_DEPTH:
        depth += 1
        # issue_objects (not the plain `objects`/default manager) so
        # soft-deleted and triage rows never enter the tree.
        children = list(
            Issue.issue_objects.filter(parent_id__in=frontier)
            .exclude(id__in=visited)
            .select_related("state", "project")
        )
        if not children:
            break

        next_frontier = []
        for child in children:
            visited.add(child.id)
            # Prune-at-terminal (Phase 0, 2026-08-28): a child already in a
            # terminal group is recorded in `traversed_ids` but its own
            # children are never enqueued. Reaching past a terminal node
            # would silently override the decision that branch is settled.
            if (child.state.group if child.state else None) in TERMINAL_GROUPS:
                traversed_ids.add(str(child.id))
            else:
                next_frontier.append(child.id)
                raw_nodes.append((child, depth))

        frontier = next_frontier

    if frontier and depth >= MAX_DEPTH:
        depth_capped = True
        logger.warning(
            "cascade_ext: MAX_DEPTH (%s) cap hit walking seed set of size %s",
            MAX_DEPTH,
            len(seed_ids),
        )

    project_ids = {child.project_id for child, _ in raw_nodes}

    # One query resolves every touched project's target state at once
    # (phase file § Implementation step 5). `State.default` is NOT usable —
    # it marks the project's default ENTRY state, normally unstarted.
    target_states: dict[uuid.UUID, State] = {}
    for candidate in State.objects.filter(
        project_id__in=project_ids, group=target_group
    ).order_by("sequence"):
        # setdefault keeps the FIRST (lowest-sequence) state per project.
        target_states.setdefault(candidate.project_id, candidate)

    # One membership query for all projects touched (phase file step 6).
    # Plain active membership — not role-gated — mirrors Decision 8's
    # wording ("the actor is not an active member").
    member_project_ids = set(
        ProjectMember.objects.filter(
            member_id=actor_id, is_active=True, project_id__in=project_ids
        ).values_list("project_id", flat=True)
    )

    descendants = []
    for child, node_depth in raw_nodes:
        state = child.state
        target_state = target_states.get(child.project_id)
        is_member = child.project_id in member_project_ids

        eligible = True
        reason = None
        if target_state is None:
            eligible = False
            reason = "no_matching_state"
        elif not is_member:
            eligible = False
            reason = "no_permission"

        descendants.append(
            {
                "id": str(child.id),
                "identifier": f"{child.project.identifier}-{child.sequence_id}",
                "name": child.name,
                "depth": node_depth,
                "project_id": str(child.project_id),
                "project_name": child.project.name,
                "state_id": str(state.id) if state else None,
                "state_name": state.name if state else None,
                "state_group": state.group if state else None,
                "target_state_id": str(target_state.id) if target_state else None,
                "eligible": eligible,
                "reason": reason,
            }
        )

    return {
        "descendants": descendants,
        "depth_capped": depth_capped,
        "traversed_ids": traversed_ids,
    }


def collect_descendants(*, root_issue, target_group: str, actor_id) -> dict:
    """Level-order BFS over every live descendant of `root_issue`.

    Shared verbatim by preview and apply so the two can never disagree on
    what is eligible (phase file § Implementation). Returns:

        {
          "descendants": [ {id, identifier, name, depth, project_id,
                             project_name, state_id, state_name,
                             state_group, target_state_id, eligible,
                             reason}, ... ],
          "depth_capped": bool,
          "traversed_ids": {str(id), ...}
        }

    As of Phase 0 (2026-08-28) the walk PRUNES at terminal nodes: an
    already-terminal descendant is excluded from `descendants`, is NOT
    traversed through (its own live descendants are consequently not listed,
    not walked, and not changed), and is still recorded in `traversed_ids`
    so apply() can tell "already terminal" apart from "never part of this
    tree".
    """
    return _collect_from_seeds(
        seed_ids={root_issue.id},
        include_seeds=False,
        target_group=target_group,
        actor_id=actor_id,
    )


def _collect_module_cascade(*, module, target_group, actor_id) -> dict:
    """Internal module-cascade shape shared by preview and apply.

    The wire `collect_module_cascade` strips `traversed_ids`; `apply` reads
    it here so both callers cannot disagree on what is eligible.
    """
    seed_ids = {
        issue_id
        for issue_id in Issue.issue_objects.filter(
            issue_module__module_id=module.id,
            issue_module__deleted_at__isnull=True,
        ).values_list("id", flat=True)
    }

    if not seed_ids:
        return {
            "target_group": target_group,
            "depth_capped": False,
            "over_cap": False,
            "cap": MAX_MODULE_CASCADE_ITEMS,
            "summary": {
                "total_live": 0,
                "eligible": 0,
                "ineligible": 0,
                "already_terminal": 0,
            },
            "items": [],
            "traversed_ids": set(),
        }

    collected = _collect_from_seeds(
        seed_ids=seed_ids,
        include_seeds=True,
        target_group=target_group,
        actor_id=actor_id,
    )

    rows = collected["descendants"]
    seed_str_ids = {str(i) for i in seed_ids}
    row_ids = {row["id"] for row in rows}

    items = []
    for node in rows:
        item = dict(node)
        # A descendant may *also* be a module member — emitted explicitly
        # rather than inferred from `depth == 0` (Phase 1 § Endpoint contract).
        item["is_module_member"] = node["id"] in seed_str_ids
        items.append(item)

    # `already_terminal` counts the terminal nodes ACTUALLY encountered (plan
    # M8 / Phase 1 § Implementation step 3) — seeds included, descendants
    # included, and NOT a subtraction from a traversal total, which under
    # pruning would silently report zero for a branch nobody walked. Every
    # terminal node the walk touched is in `traversed_ids`; live seeds and
    # live descendants are both in `rows`. A terminal SEED is also a member
    # hence `seed_str_ids - row_ids` is exactly the terminal seeds.
    already_terminal = len(
        (collected["traversed_ids"] - row_ids) | (seed_str_ids - row_ids)
    )

    eligible = sum(1 for node in items if node["eligible"])
    ineligible = len(items) - eligible

    summary = {
        "total_live": len(items),
        "eligible": eligible,
        "ineligible": ineligible,
        "already_terminal": already_terminal,
    }

    over_cap = summary["total_live"] > MAX_MODULE_CASCADE_ITEMS
    if over_cap:
        # Do NOT truncate — a truncated list silently under-reports what a
        # confirm would write, which is the failure the cap exists to avoid.
        items = []

    return {
        "target_group": target_group,
        "depth_capped": collected["depth_capped"],
        "over_cap": over_cap,
        "cap": MAX_MODULE_CASCADE_ITEMS,
        "summary": summary,
        "items": items,
        "traversed_ids": collected["traversed_ids"],
    }


def collect_module_cascade(*, module, target_group, actor_id) -> dict:
    """Preview-shape for cascading a module's terminal status onto its issues.

    Seed set = every live module member via the canonical soft-delete-aware
    query (`Issue.issue_objects` + non-deleted `ModuleIssue` rows — never
    `module.issue_module.all()`), then the shared BFS with the seeds
    themselves as depth-0 candidates. Everything beneath a terminal member is
    pruned (Phase 0's rule, shared with the issue cascade).

    Returns the wire shape for GET .../cascade-preview/ (no `traversed_ids`):
    target_group, depth_capped, over_cap, cap, items, summary.
    """
    collected = _collect_module_cascade(
        module=module, target_group=target_group, actor_id=actor_id
    )
    collected.pop("traversed_ids", None)
    return collected


def apply_module_cascade(
    *, module, status, item_ids, actor_id, slug, origin
) -> dict:
    """Apply a module's new `status` plus a caller-selected subset of its
    currently-eligible issues, atomically (plan M5).

    `item_ids` is a REQUEST, never an authorization:
    `item_ids=None` -> every currently-eligible item (headless/MCP callers).
    `item_ids=[]`   -> nothing cascades; only the module's status moves.

    Raises CascadeCapExceeded BEFORE opening any transaction when the live
    count exceeds MAX_MODULE_CASCADE_ITEMS, so nothing — the module's own
    status included — is written.
    """
    target_group = MODULE_STATUS_TO_STATE_GROUP[status]

    collected = _collect_module_cascade(
        module=module, target_group=target_group, actor_id=actor_id
    )
    if collected["over_cap"]:
        raise CascadeCapExceeded(collected["summary"]["total_live"])

    by_id = {node["id"]: node for node in collected["items"]}
    eligible_ids = {cid for cid, node in by_id.items() if node["eligible"]}
    traversed_ids = collected["traversed_ids"]

    if item_ids is None:
        requested_ids = set(eligible_ids)
    else:
        requested_ids = {str(cid) for cid in item_ids}

    accepted_ids = requested_ids & eligible_ids

    rejected = []
    for cid in sorted(requested_ids - accepted_ids):
        node = by_id.get(cid)
        if node is not None:
            reason = node["reason"] or "not_eligible"
        elif cid in traversed_ids:
            # A terminal node the walk encountered but never emitted.
            reason = "already_terminal"
        elif _has_terminal_ancestor_to_root(
            issue_id=cid, traversed_ids=traversed_ids
        ):
            # Phase 0's reason, reused verbatim: a live id the walk refused
            # to reach because a terminal node prunes its branch.
            reason = "under_terminal_ancestor"
        else:
            reason = "not_in_module_tree"
        rejected.append({"id": cid, "reason": reason})

    accepted_nodes = [by_id[cid] for cid in accepted_ids]

    old_status = module.status
    now = timezone.now()

    # Module write + every cascaded issue write share ONE transaction (M5) —
    # a mid-way failure rolls the module's status change back too.
    with transaction.atomic():
        module.status = status
        module.updated_at = now
        module.save(update_fields=["status", "updated_at"])

        if accepted_nodes:
            issues = list(Issue.issue_objects.filter(id__in=list(accepted_ids)))
            for issue in issues:
                issue.state_id = by_id[str(issue.id)]["target_state_id"]
                issue.updated_at = now

            for start in range(0, len(issues), _BULK_UPDATE_BATCH):
                batch = issues[start : start + _BULK_UPDATE_BATCH]
                # bulk_update skips save(), so updated_at is set explicitly above.
                Issue.issue_objects.bulk_update(batch, ["state_id", "updated_at"])

    # Dispatched only once the atomic block above has committed — a
    # mid-transaction failure never reaches here.
    model_activity.delay(
        model_name="module",
        model_id=str(module.id),
        requested_data={"status": status},
        current_instance=json.dumps({"status": old_status}),
        actor_id=actor_id,
        slug=slug,
        origin=origin,
    )

    epoch = int(now.timestamp())
    for node in accepted_nodes:
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"state_id": node["target_state_id"]}),
            actor_id=str(actor_id),
            issue_id=node["id"],
            project_id=node["project_id"],
            current_instance=json.dumps({"state_id": node["state_id"]}),
            epoch=epoch,
            # notification=False is load-bearing (M11), not a typo — only the
            # module's own change fires; a 200-item cascade must not fire 200
            # watcher notifications.
            notification=False,
            origin=origin,
        )
        model_activity.delay(
            model_name="issue",
            model_id=node["id"],
            requested_data={"state": node["target_state_id"]},
            current_instance=json.dumps({"state": node["state_id"]}),
            actor_id=actor_id,
            slug=slug,
            origin=origin,
        )

    return {
        "module": str(module.id),
        "status": status,
        "updated": sorted(accepted_ids),
        "rejected": rejected,
    }


def apply_cascade(*, root_issue, state, child_ids, actor_id, slug, origin) -> dict:
    """Apply the parent's new `state` plus a caller-selected subset of
    currently-eligible descendants, atomically.

    `child_ids` is a REQUEST, never an authorization (risk-15 in the plan):
    eligibility is re-derived here from scratch via `collect_descendants`,
    and anything posted that isn't currently eligible lands in `rejected`
    rather than being silently applied or silently dropped.

    - `child_ids=None` -> every currently-eligible descendant (Decision 14).
    - `child_ids=[]` -> nothing cascades; only the parent moves (an explicit
      empty list is NOT "all").
    """
    old_state = root_issue.state
    target_group = resolve_target_group(old_state, state)

    if target_group is not None:
        collected = collect_descendants(
            root_issue=root_issue, target_group=target_group, actor_id=actor_id
        )
    else:
        # Not actually a cascade-triggering move (e.g. re-applying within the
        # same terminal group) — the parent still writes, nothing to cascade.
        collected = {"descendants": [], "depth_capped": False, "traversed_ids": set()}

    by_id = {node["id"]: node for node in collected["descendants"]}
    eligible_ids = {cid for cid, node in by_id.items() if node["eligible"]}

    if child_ids is None:
        requested_ids = set(eligible_ids)
    else:
        requested_ids = {str(cid) for cid in child_ids}

    accepted_ids = requested_ids & eligible_ids

    traversed_ids = collected["traversed_ids"]
    rejected = []
    for cid in sorted(requested_ids - accepted_ids):
        node = by_id.get(cid)
        if node is not None:
            reason = node["reason"] or "not_eligible"
        elif cid in traversed_ids:
            reason = "already_terminal"
        elif _has_terminal_ancestor_to_root(
            issue_id=cid, traversed_ids=traversed_ids
        ):
            # Phase 0: a live descendant beneath a pruned terminal branch.
            reason = "under_terminal_ancestor"
        else:
            reason = "not_a_descendant"
        rejected.append({"id": cid, "reason": reason})

    accepted_nodes = [by_id[cid] for cid in accepted_ids]

    pre_update_state_id = root_issue.state_id
    epoch = int(timezone.now().timestamp())

    # Parent write + every cascaded child write share ONE transaction
    # (Decision 9) — a mid-way failure (e.g. the bulk_update below) rolls
    # the parent's state change back too.
    with transaction.atomic():
        root_issue.state = state
        root_issue.updated_at = timezone.now()
        root_issue.save(update_fields=["state", "updated_at"])

        if accepted_nodes:
            now = timezone.now()
            children = list(Issue.issue_objects.filter(id__in=list(accepted_ids)))
            for child in children:
                node = by_id[str(child.id)]
                child.state_id = node["target_state_id"]
                child.updated_at = now

            for start in range(0, len(children), _BULK_UPDATE_BATCH):
                batch = children[start : start + _BULK_UPDATE_BATCH]
                # bulk_update skips save(), so updated_at is set explicitly above.
                Issue.issue_objects.bulk_update(batch, ["state_id", "updated_at"])

    # Dispatched only once the atomic block above has committed (this app
    # has no ATOMIC_REQUESTS wrapper, so exiting `with` above commits
    # immediately) — a mid-transaction failure never reaches here.
    issue_activity.delay(
        type="issue.activity.updated",
        requested_data=json.dumps({"state_id": str(state.id)}),
        actor_id=str(actor_id),
        issue_id=str(root_issue.id),
        project_id=str(root_issue.project_id),
        current_instance=json.dumps(
            {"state_id": str(pre_update_state_id) if pre_update_state_id else None}
        ),
        epoch=epoch,
        notification=True,
        origin=origin,
    )
    model_activity.delay(
        model_name="issue",
        model_id=str(root_issue.id),
        requested_data={"state": str(state.id)},
        current_instance=json.dumps(
            {"state": str(pre_update_state_id) if pre_update_state_id else None}
        ),
        actor_id=actor_id,
        slug=slug,
        origin=origin,
    )

    for node in accepted_nodes:
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"state_id": node["target_state_id"]}),
            actor_id=str(actor_id),
            issue_id=node["id"],
            project_id=node["project_id"],
            current_instance=json.dumps({"state_id": node["state_id"]}),
            epoch=epoch,
            # notification=False is load-bearing (Decision 10), not a typo —
            # only the parent's own change notifies watchers. A 20-child
            # cascade must not fire 20 watcher notifications.
            notification=False,
            origin=origin,
        )
        model_activity.delay(
            model_name="issue",
            model_id=node["id"],
            requested_data={"state": node["target_state_id"]},
            current_instance=json.dumps({"state": node["state_id"]}),
            actor_id=actor_id,
            slug=slug,
            origin=origin,
        )

    return {
        "parent": str(root_issue.id),
        "updated": sorted(accepted_ids),
        "rejected": rejected,
    }