# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Version-bump receivers.
#
# WHY SIGNALS AND NOT ENDPOINT CALLS: the majority of invalidating writes happen
# in CORE code this fork does not own — measured 2026-08-26, 22.31 issue
# writes/hour against 11.29 estimate writes/hour in the busiest workspace.
# Calling bump_workspace() from plane/workload/views.py would cover only the
# fork's own write endpoints and silently miss every edit made through core's
# issue views. A missed bump does not fail loudly; it serves stale data that
# looks fresh. Signals are the only placement that covers both.
#
# The model list below is derived from the 13 queries compute_workload actually
# runs. Each model here is READ by the endpoint, so a change to it can change
# the response. See plans/260826-redis-cache-workload-perf/phase-3.md.

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from plane.db.models import Issue, IssueAssignee, ProjectMember, State, Workspace

from .cache import bump_workspace
from ..workload.models import WorkloadEstimate, WorkloadSettings

logger = logging.getLogger(__name__)


def _slug_for_workspace_id(workspace_id):
    """Resolve a workspace slug from its id.

    One indexed PK lookup per write. Measured 2026-08-26: 0.367 ms, against a
    0.717 ms bare Issue.save() and a measured write rate of ~58/hour across all
    workspaces — about 21 ms of database time per hour in total.

    An earlier draft of phase-3.md called for a memo to avoid this query. That
    guidance was written before the cost was measured and is wrong: a process-
    local memo goes stale on a workspace rename in every worker except the one
    that handled it, and signals are in-process only, so those workers would
    bump the old slug forever while reads under the new slug were never
    invalidated. Reading fresh is both simpler and the only variant that cannot
    silently serve stale data.
    """
    if workspace_id is None:
        return None
    return Workspace.objects.filter(pk=workspace_id).values_list("slug", flat=True).first()


def _bump_from_workspace_id(workspace_id, source):
    slug = _slug_for_workspace_id(workspace_id)
    if slug is None:
        # The workspace row is gone (cascade delete). Nothing can read its
        # cache any more, so there is nothing to invalidate.
        return
    try:
        bump_workspace(slug)
    except Exception:
        # bump_workspace is deliberately fail-loud, but a signal receiver that
        # raises would abort the caller's transaction — turning a cache problem
        # into a failed user write. Log loudly and let the write land; the
        # entry is stale until the next bump, which is strictly better than
        # losing the write itself.
        logger.error(
            "workload_cache: version bump FAILED for workspace=%s (via %s) — "
            "cached responses for this workspace are now STALE until the next "
            "successful write",
            slug,
            source,
            exc_info=True,
        )


# --- models carrying workspace_id directly (ProjectBaseModel or explicit FK) ---

@receiver(post_save, sender=Issue)
@receiver(post_delete, sender=Issue)
def _on_issue(sender, instance, **kwargs):
    # start_date / target_date / state / name all appear on a timeline bar.
    _bump_from_workspace_id(instance.workspace_id, "Issue")


@receiver(post_save, sender=IssueAssignee)
@receiver(post_delete, sender=IssueAssignee)
def _on_issue_assignee(sender, instance, **kwargs):
    # Decides which swimlane a bar sits in.
    _bump_from_workspace_id(instance.workspace_id, "IssueAssignee")


@receiver(post_save, sender=ProjectMember)
@receiver(post_delete, sender=ProjectMember)
def _on_project_member(sender, instance, **kwargs):
    # Every active member gets a row whether or not they carry work, so
    # membership changes the response even with no issue touched.
    _bump_from_workspace_id(instance.workspace_id, "ProjectMember")


@receiver(post_save, sender=State)
@receiver(post_delete, sender=State)
def _on_state(sender, instance, **kwargs):
    # state_name / state_color are painted onto every bar.
    _bump_from_workspace_id(instance.workspace_id, "State")


@receiver(post_save, sender=WorkloadEstimate)
@receiver(post_delete, sender=WorkloadEstimate)
def _on_workload_estimate(sender, instance, **kwargs):
    _bump_from_workspace_id(instance.workspace_id, "WorkloadEstimate")


@receiver(post_save, sender=WorkloadSettings)
@receiver(post_delete, sender=WorkloadSettings)
def _on_workload_settings(sender, instance, **kwargs):
    # max_daily_hours / workdays / week_start_day drive every capacity figure.
    _bump_from_workspace_id(instance.workspace_id, "WorkloadSettings")


# --- Workspace itself: has the slug directly, no lookup needed ---

@receiver(post_save, sender=Workspace)
def _on_workspace(sender, instance, **kwargs):
    # `timezone` sets the workspace-local "today", which drives every `overdue`
    # flag. A rename also lands here, and bumping the NEW slug is correct: the
    # old slug's entries become unreachable because nothing requests it.
    try:
        bump_workspace(instance.slug)
    except Exception:
        logger.error(
            "workload_cache: version bump FAILED for workspace=%s (via Workspace) — "
            "cached responses are now STALE until the next successful write",
            instance.slug,
            exc_info=True,
        )
