# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Cascade logic — level-order BFS descendant collection shared by both the
# preview and apply endpoints (docs/FORK.md touch-point 2, no core view
# edited). Contract, decisions, and test matrix:
# plans/260822-cascade-complete-sub-items/phase-1-cascade-backend.md

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
          "traversed_ids": {str(id), ...}   # every node visited except the
                                             # root, INCLUDING already-terminal
                                             # ones — used by apply() to tell
                                             # "already terminal" apart from
                                             # "never part of this tree".
        }

    Already-terminal descendants (Decision 5) are excluded from
    `descendants` but are still traversed through, so their own live
    descendants remain reachable — and still recorded in `traversed_ids`.
    """
    visited = {root_issue.id}
    frontier = [root_issue.id]
    depth = 0
    raw_nodes = []  # [(Issue, depth), ...] in level order
    depth_capped = False

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
            next_frontier.append(child.id)
            raw_nodes.append((child, depth))
        frontier = next_frontier

    if frontier and depth >= MAX_DEPTH:
        depth_capped = True
        logger.warning(
            "cascade_ext: MAX_DEPTH (%s) cap hit walking descendants of issue %s",
            MAX_DEPTH,
            root_issue.id,
        )

    traversed_ids = {str(child.id) for child, _ in raw_nodes}

    # Terminal nodes (either group — regardless of `target_group`) are
    # excluded from the result but were already pushed to `frontier` above,
    # so their own live descendants were still traversed.
    live_nodes = [
        (child, node_depth)
        for child, node_depth in raw_nodes
        if (child.state.group if child.state else None) not in TERMINAL_GROUPS
    ]

    project_ids = {child.project_id for child, _ in live_nodes}

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
    for child, node_depth in live_nodes:
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

    rejected = []
    for cid in sorted(requested_ids - accepted_ids):
        node = by_id.get(cid)
        if node is not None:
            reason = node["reason"] or "not_eligible"
        elif cid in collected["traversed_ids"]:
            reason = "already_terminal"
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
