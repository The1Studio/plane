# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork (work-item creation defaults).
#
# Every decision behind "a work item created with a field unset gets a
# default" lives here as a pure function, so the two core serializers that
# call in (plane/app/serializers/issue.py, plane/api/serializers/issue.py)
# carry a single fenced call each and nothing more — the rebase-conflict
# budget in docs/FORK.md is what makes that worth doing.
#
# Why this cannot be a post_save signal, which would need no core edit at
# all: a signal sees only the saved row, where an ABSENT target_date and an
# EXPLICIT null are both None. The whole contract turns on telling those
# apart, and only a serializer can — it still has self.initial_data.
#
# Contract: plans/260824-workitem-creation-defaults/phase-2.md

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from plane.db.models import ProjectMember

# Mirrors the role floor the core serializers already use when validating
# assignees (plane/app/serializers/issue.py) — a member below it cannot be
# assigned work, so defaulting to them would create an unreachable item.
ASSIGNABLE_ROLE_FLOOR = 15


def local_today(user) -> date:
    """Today's date in ``user``'s own timezone, falling back to UTC.

    The browser prefills the due-date pill with the viewer's LOCAL date. If
    the server defaulted in UTC the two would disagree by a day for every
    user east of UTC creating a work item before their local 07:00 — the
    studio sits at UTC+7, so that is the common case, not the edge one.
    """
    tzname = getattr(user, "user_timezone", None) or "UTC"
    try:
        tz = ZoneInfo(tzname)
    except (ZoneInfoNotFoundError, ValueError):
        # A malformed stored timezone must not 500 a work-item create.
        tz = ZoneInfo("UTC")
    return timezone.localtime(timezone.now(), tz).date()


def _defaults_enabled(context) -> bool:
    """False only where a caller opted out (intake, today)."""
    return bool((context or {}).get("apply_creation_defaults", True))


def _is_assignable(*, user_id, project_id) -> bool:
    if user_id is None or project_id is None:
        return False
    return ProjectMember.objects.filter(
        member_id=user_id,
        project_id=project_id,
        role__gte=ASSIGNABLE_ROLE_FLOOR,
        is_active=True,
    ).exists()


def resolve_creation_target_date(*, is_create, initial_data, context, start_date, user):
    """The date to write to ``target_date``, or None to leave the payload alone.

    Returns None — meaning "do not touch it" — when the field was supplied at
    all. An explicit ``null`` is a deliberate "no due date" and is honoured;
    only a payload with no ``target_date`` key is treated as unset.
    """
    if not is_create:
        return None
    if not _defaults_enabled(context):
        return None
    if "target_date" in (initial_data or {}):
        return None

    today = local_today(user)
    # Never manufacture a payload that the serializer's own
    # "Start date cannot exceed target date" check would then reject: a
    # request that succeeds today must not start failing.
    if start_date is not None and start_date > today:
        return start_date
    return today


def resolve_creation_assignee_id(
    *,
    initial_data,
    context,
    project_id,
    default_assignee_id,
    created_by_id,
    assignee_field,
):
    """The single assignee id to create, or None to leave it unassigned.

    Called only where the payload named no assignees, so the whole job is
    picking the fallback. Order:

    1. The project's own ``default_assignee``, when still assignable. This
       clause is transcribed from the core block it replaces, so a project
       that has configured a default assignee behaves exactly as before —
       including on an explicit empty list, which upstream already treats as
       "use the default".
    2. The creator, but only when the assignee field was ABSENT. An explicit
       ``[]`` means "nobody" and stops here.

    ``assignee_field`` differs between the two serializers ("assignee_ids" in
    the app one, "assignees" in the public API one). Passing the wrong name
    fails silently — the fallback simply never fires — which is why it is a
    required argument rather than a default.
    """
    if not _defaults_enabled(context):
        return None

    if default_assignee_id is not None and _is_assignable(
        user_id=default_assignee_id, project_id=project_id
    ):
        return default_assignee_id

    if assignee_field in (initial_data or {}):
        return None

    if _is_assignable(user_id=created_by_id, project_id=project_id):
        return created_by_id

    return None
