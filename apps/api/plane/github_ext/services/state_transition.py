# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P2 — status automation core. Resolves the configured target state for a
# GitHub PR-lifecycle event and applies it via a SERVICE-TOKEN INTERNAL API
# CALL — never a raw `issue.save()`.
#
# Why the API call (trap #4, phase-P2.md): a bare `issue.save()` inside this
# fork app would change the row but SILENTLY skip IssueActivity, notifications,
# and the outbound webhook (those live in the core issue viewset, not in
# save()). Instead we PATCH Plane's own public work-item endpoint
# (IssueDetailAPIEndpoint, plane/api/views/issue.py — its patch() fires
# issue_activity.delay + model_activity.delay) authenticated with the bot's
# service APIToken (X-Api-Key). We do this IN-PROCESS via APIRequestFactory —
# it runs the exact same view code as a real HTTP call, firing every
# side-effect, but without a self-network-hop (simpler + unit-testable). This
# is the "service-token internal API call" the plan specifies, realized
# in-process.

import logging

logger = logging.getLogger("plane.github_ext")

# Built-in defaults (overridable per-project or globally via
# StateTransitionConfig.rules). Values are state NAMES for the started-group
# transitions; the merged→Done transition resolves by group="completed".
DEFAULT_RULES = {
    "pr_opened": "In Progress",
    "pr_ready_for_review": "In Review",
    "pr_merged": "Done",
}

# Event keys the rules map is allowed to carry (used for PUT validation).
EVENT_KEYS = tuple(DEFAULT_RULES.keys())


def resolve_workspace_config(workspace_id):
    """Return the effective event→state-name rules for a workspace, before any
    per-project override.

    Precedence: built-in `DEFAULT_RULES` → the instance-wide `scope="global"`
    row → the `scope="workspace"` row for this workspace. Each partial rules
    dict is merged over the lower tier.
    """
    from plane.github_ext.models import StateTransitionConfig

    rules = dict(DEFAULT_RULES)

    global_row = StateTransitionConfig.objects.filter(scope="global").first()
    if global_row and global_row.rules:
        rules.update(global_row.rules)

    workspace_row = StateTransitionConfig.objects.filter(
        scope="workspace", workspace_id=workspace_id
    ).first()
    if workspace_row and workspace_row.rules:
        rules.update(workspace_row.rules)

    return rules


def resolve_config(project):
    """Return the effective event→state-name rules for `project`.

    Three-tier precedence (deterministic): built-in `DEFAULT_RULES` → the
    instance-wide `scope="global"` row → the `scope="workspace"` row for this
    project's workspace → the `scope="project"` row for this project. Each
    partial rules dict is merged over the lower tiers, so an override need only
    specify the events it changes.
    """
    from plane.github_ext.models import StateTransitionConfig

    rules = resolve_workspace_config(project.workspace_id)

    project_row = StateTransitionConfig.objects.filter(
        scope="project", project_id=project.id
    ).first()
    if project_row and project_row.rules:
        rules.update(project_row.rules)

    return rules


def resolve_target_state(project, event_key):
    """Resolve the concrete `State` for a transition event within `project`.

    - `pr_merged` → the project's first `completed`-group state (Done).
    - `pr_opened` / `pr_ready_for_review` → the configured state NAME if it
      exists in the project, else the first `started`-group state.

    Returns `None` (caller logs + skips, never crashes) when the project has
    no suitable state — e.g. no `completed`-group state exists.
    """
    from plane.db.models import State

    if event_key == "pr_merged":
        return (
            State.objects.filter(project_id=project.id, group="completed")
            .order_by("sequence")
            .first()
        )

    rules = resolve_config(project)
    configured_name = rules.get(event_key)
    if configured_name:
        by_name = State.objects.filter(
            project_id=project.id, name__iexact=configured_name
        ).first()
        if by_name:
            return by_name

    # Fallback: first started-group state (In Progress / In Review both live
    # in the started group).
    return (
        State.objects.filter(project_id=project.id, group="started")
        .order_by("sequence")
        .first()
    )


def get_service_credentials(installation):
    """Resolve the (bot_user, service_token) for an installation's workspace
    from its `WorkspaceIntegration` (actor + api_token FK slots — no new
    column, phase-P2.md). Returns `(None, None)` if not bootstrapped.
    """
    from plane.db.models import WorkspaceIntegration

    wi = (
        WorkspaceIntegration.objects.select_related("actor", "api_token")
        .filter(workspace_id=installation.workspace_id, integration__provider="github")
        .first()
    )
    if wi is None or wi.api_token is None:
        logger.warning(
            "get_service_credentials: no github WorkspaceIntegration/api_token for "
            "workspace=%s (installation=%s) - cannot transition",
            installation.workspace_id,
            installation.installation_id,
        )
        return None, None
    return wi.actor, wi.api_token.token


def ensure_bot_membership(bot_user, project):
    """Make the integration bot a Workspace + Project member so the
    service-token PATCH passes `ProjectEntityPermission` on the core issue
    endpoint. Idempotent; role 15 (Member) is enough to update issues.

    Without this, every transition would 403 — the bot is authenticated but
    not authorized on the project. Runs once per (bot, project) via
    get_or_create.
    """
    if bot_user is None or project is None:
        return
    from plane.db.models import ProjectMember, WorkspaceMember

    WorkspaceMember.objects.get_or_create(
        workspace_id=project.workspace_id,
        member=bot_user,
        defaults={"role": 15},
    )
    ProjectMember.objects.get_or_create(
        workspace_id=project.workspace_id,
        project_id=project.id,
        member=bot_user,
        defaults={"role": 15},
    )


def apply_transition(issue, target_state, service_token):
    """Move `issue` to `target_state` via the public work-item API using the
    service token — firing IssueActivity/notifications/webhook (trap #4 fix).

    In-process APIRequestFactory dispatch of IssueDetailAPIEndpoint.patch;
    returns the HTTP status code (200 on success). Never calls issue.save().
    """
    from rest_framework.test import APIRequestFactory

    from plane.api.views.issue import IssueDetailAPIEndpoint

    if target_state is None or not service_token:
        return None

    slug = issue.workspace.slug
    path = f"/api/v1/workspaces/{slug}/projects/{issue.project_id}/issues/{issue.id}/"
    factory = APIRequestFactory()
    request = factory.patch(
        path,
        {"state": str(target_state.id)},
        format="json",
        HTTP_X_API_KEY=service_token,
    )
    view = IssueDetailAPIEndpoint.as_view(http_method_names=["get", "patch", "delete"])
    response = view(request, slug=slug, project_id=str(issue.project_id), pk=str(issue.id))
    if hasattr(response, "render"):
        response.render()

    if response.status_code != 200:
        logger.warning(
            "apply_transition: issue=%s -> state=%s failed (HTTP %s): %s",
            issue.id,
            target_state.id,
            response.status_code,
            getattr(response, "data", b""),
        )
    return response.status_code
