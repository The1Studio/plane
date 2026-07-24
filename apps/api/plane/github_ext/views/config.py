# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P2/P4 — status-automation config CRUD (github_ext). Three-tier scoping,
# resolved most-specific-wins by services/state_transition.py:
#
#   instance-global  ->  per-workspace  ->  per-project
#
# Each tier is a separate endpoint with the matching permission level:
#
#   GET/PUT /api/github/config/                              (INSTANCE admin)
#       The single scope="global" row — the instance-wide default rules.
#       Gated by InstanceAdminPermission because one row is shared by every
#       workspace on the instance; a per-workspace admin must NOT be able to
#       change what other workspaces inherit.
#
#   GET/PUT /api/github/<slug>/config/                       (workspace admin)
#       The scope="workspace" row for <slug>. GET returns the resolved
#       defaults->global->workspace rules; PUT upserts this workspace's
#       override. Validated for shape only — a workspace override is
#       project-agnostic (state NAMES, not a specific project's State rows),
#       so state existence is checked at the project tier, not here.
#
#   GET/PUT /api/github/<slug>/projects/<uuid:project_id>/config/  (ws admin)
#       The scope="project" row. GET returns the fully-resolved effective
#       rules for the project; PUT upserts the override and validates each
#       state NAME exists in the project. The <slug> in the path MUST own
#       <project_id> (guarded in initial()) so the workspace-role gate can't
#       be satisfied against an unrelated workspace.
#
# Workspace-tier views scope the shared @allow_permission(level="WORKSPACE")
# decorator (plane/app/permissions/base.py) via a real <str:slug> path
# segment — no more query-param slug injection. The global view uses DRF
# permission_classes = [InstanceAdminPermission] directly (no slug at all).
#
# Shared handlers — reused by both the app API (this module, session-auth)
# and the public API (../api_views.py, API-key auth), so the resolution +
# validation + persistence logic lives in exactly one place. Mirrors the
# workload/views.py + workload/api_views.py split.

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, State
from plane.github_ext.models import StateTransitionConfig
from plane.github_ext.services.state_transition import (
    DEFAULT_RULES,
    EVENT_KEYS,
    resolve_config,
    resolve_workspace_config,
)
from plane.license.api.permissions import InstanceAdminPermission


def _validate_rules_shape(rules):
    """Shared shape validation for a PUT `rules` payload: must be a dict,
    every key must be a known EVENT_KEYS event, every value a non-empty
    string. Returns an error message string, or `None` when valid.
    """
    if not isinstance(rules, dict):
        return "rules must be an object"
    for key, value in rules.items():
        if key not in EVENT_KEYS:
            return f"invalid event key '{key}'"
        if not isinstance(value, str) or not value.strip():
            return f"value for '{key}' must be a non-empty string"
    return None


def resolve_workspace_or_404(slug):
    """Look up a `Workspace` by slug, or raise DRF `NotFound` (404)."""
    from plane.db.models import Workspace

    workspace = Workspace.objects.filter(slug=slug).first()
    if workspace is None:
        raise NotFound("workspace not found")
    return workspace


def resolve_project_or_404(slug, project_id):
    """Look up a `Project` by id, requiring it belong to workspace `slug`
    (cross-workspace guard), or raise DRF `NotFound` (404)."""
    project = (
        Project.objects.filter(id=project_id).select_related("workspace").first()
    )
    if project is None or project.workspace.slug != slug:
        raise NotFound("project not found")
    return project


def global_config_get():
    """Return the resolved scope="global" rules (DEFAULT_RULES merged with
    the stored override, if any)."""
    rules = dict(DEFAULT_RULES)
    row = StateTransitionConfig.objects.filter(scope="global").first()
    if row and row.rules:
        rules.update(row.rules)
    return rules


def global_config_put(rules_payload):
    """Validate + upsert the scope="global" row.

    Returns `(rules, error)` — on success `error` is `None` and `rules` is
    the saved dict; on validation failure `rules` is `None` and `error` is
    the message string (caller maps it to HTTP 400).
    """
    error = _validate_rules_shape(rules_payload)
    if error:
        return None, error

    row = StateTransitionConfig.objects.filter(scope="global").first()
    if row is None:
        row = StateTransitionConfig(scope="global")
    row.rules = rules_payload
    row.save()
    return row.rules, None


def workspace_config_get(workspace):
    """Return the resolved (defaults→global→workspace) rules for `workspace`."""
    return resolve_workspace_config(workspace.id)


def workspace_config_put(workspace, rules_payload):
    """Validate (shape-only) + upsert the scope="workspace" row for
    `workspace`. Same `(rules, error)` contract as `global_config_put`."""
    error = _validate_rules_shape(rules_payload)
    if error:
        return None, error

    row = StateTransitionConfig.objects.filter(
        scope="workspace", workspace_id=workspace.id
    ).first()
    if row is None:
        row = StateTransitionConfig(scope="workspace", workspace=workspace)
    row.rules = rules_payload
    row.save()
    return row.rules, None


def project_config_get(project):
    """Return the fully-resolved effective rules for `project`."""
    return resolve_config(project)


def project_config_put(project, rules_payload):
    """Validate (shape + state-name existence) + upsert the scope="project"
    row for `project`. Same `(rules, error)` contract as `global_config_put`."""
    error = _validate_rules_shape(rules_payload)
    if error:
        return None, error

    for key, value in rules_payload.items():
        if not State.objects.filter(project_id=project.id, name__iexact=value).exists():
            return None, f"state '{value}' not found in project"

    row = StateTransitionConfig.objects.filter(
        scope="project", project_id=project.id
    ).first()
    if row is None:
        row = StateTransitionConfig(scope="project", project=project)
    row.rules = rules_payload
    row.save()
    return row.rules, None


class GithubGlobalConfigView(BaseAPIView):
    """Read + upsert the scope="global" StateTransitionConfig row — the
    instance-wide default rules, overridable per-workspace
    (`GithubWorkspaceConfigView`) then per-project (`GithubProjectConfigView`).

    GET /api/github/config/ — instance admin
    PUT /api/github/config/ ({"rules": {...}}) — instance admin
    """

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        return Response({"rules": global_config_get()}, status=status.HTTP_200_OK)

    def put(self, request):
        rules, error = global_config_put(request.data.get("rules"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rules": rules}, status=status.HTTP_200_OK)


class GithubWorkspaceConfigView(BaseAPIView):
    """Read the resolved (defaults→global→workspace) rules + upsert this
    workspace's scope="workspace" override row.

    GET /api/github/<slug>/config/ — any workspace member
    PUT /api/github/<slug>/config/ ({"rules": {...}}) — workspace admin

    Shape-only validation: a workspace override is project-agnostic, so state
    NAMES are not checked against any project's State rows here (that happens
    at the project tier).
    """

    def initial(self, request, *args, **kwargs):
        self._workspace = resolve_workspace_or_404(kwargs.get("slug"))
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return Response(
            {"rules": workspace_config_get(self._workspace)}, status=status.HTTP_200_OK
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        rules, error = workspace_config_put(self._workspace, request.data.get("rules"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rules": rules}, status=status.HTTP_200_OK)


class GithubProjectConfigView(BaseAPIView):
    """Read the fully-resolved effective config for a project + upsert its
    scope="project" override row.

    GET /api/github/<slug>/projects/<uuid:project_id>/config/ — any ws member
    PUT /api/github/<slug>/projects/<uuid:project_id>/config/ — workspace admin

    The <slug> in the path MUST own <project_id>; a mismatch is a 404 (before
    the role gate runs) so the workspace-role check can't be satisfied against
    an unrelated workspace.
    """

    def initial(self, request, *args, **kwargs):
        self._project = resolve_project_or_404(kwargs.get("slug"), kwargs.get("project_id"))
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, project_id):
        return Response(
            {"rules": project_config_get(self._project)}, status=status.HTTP_200_OK
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug, project_id):
        rules, error = project_config_put(self._project, request.data.get("rules"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rules": rules}, status=status.HTTP_200_OK)
