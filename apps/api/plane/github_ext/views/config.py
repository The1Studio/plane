# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P2 — status-automation config CRUD (github_ext). Mirrors ai_ext's
# BaseAPIView + @allow_permission pattern (ai_ext/views/config.py):
# `from plane.app.views.base import BaseAPIView`,
# `from plane.app.permissions import ROLE, allow_permission`, class-based
# views with `@allow_permission([ROLE.ADMIN], level="WORKSPACE")` on writes.
#
# URL-vs-permission note (deliberate deviation, documented for review): the
# shared `@allow_permission(level="WORKSPACE")` decorator
# (plane/app/permissions/base.py) reads `kwargs["slug"]` to scope its
# WorkspaceMember lookup. Neither route here carries a `<str:slug>` path
# segment (github/config/, github/projects/<uuid:project_id>/config/), so
# `initial()` is overridden on both views to resolve/inject a `slug` kwarg
# BEFORE the decorated handler runs (DRF's `APIView.dispatch()` reuses the
# same `kwargs` dict for `self.kwargs` and the eventual `handler(...)` call,
# so mutating `self.kwargs` inside `initial()` is visible to the decorator):
#
#   - GithubProjectConfigView: `project_id` is in the URL -> the project's
#     workspace slug is looked up unambiguously and injected. A missing
#     project raises `NotFound` (404) here, before the decorator runs.
#   - GithubGlobalConfigView: `StateTransitionConfig(scope="global")` has no
#     workspace FK at all (models.py) — it is a single instance-wide row, so
#     there is no URL-derivable workspace. The acting workspace (whose
#     role gates access) is instead taken from `?slug=` (GET) or the `slug`
#     field of the PUT body. A missing slug raises `ValidationError` (400).

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, State
from plane.github_ext.models import StateTransitionConfig
from plane.github_ext.services.state_transition import (
    DEFAULT_RULES,
    EVENT_KEYS,
    resolve_config,
)


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


class GithubGlobalConfigView(BaseAPIView):
    """Read + upsert the scope="global" StateTransitionConfig row (the
    instance-wide default rules, overridable per-project via
    `GithubProjectConfigView`).

    GET /api/github/config/?slug=<workspace-slug> — any workspace member
    PUT /api/github/config/ ({"slug": "...", "rules": {...}}) — admin only
    """

    def initial(self, request, *args, **kwargs):
        slug = request.query_params.get("slug") or request.data.get("slug")
        if not slug:
            raise ValidationError(
                {"slug": "slug query param (GET) or body field (PUT) is required"}
            )
        self.kwargs["slug"] = slug
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        rules = dict(DEFAULT_RULES)
        row = StateTransitionConfig.objects.filter(scope="global").first()
        if row and row.rules:
            rules.update(row.rules)
        return Response({"rules": rules}, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        rules = request.data.get("rules")
        error = _validate_rules_shape(rules)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        row = StateTransitionConfig.objects.filter(scope="global").first()
        if row is None:
            row = StateTransitionConfig(scope="global")
        row.rules = rules
        row.save()
        return Response({"rules": row.rules}, status=status.HTTP_200_OK)


class GithubProjectConfigView(BaseAPIView):
    """Read the effective (merged) config for a project + upsert its
    scope="project" override row.

    GET /api/github/projects/<uuid:project_id>/config/ — any workspace member
    PUT /api/github/projects/<uuid:project_id>/config/ ({"rules": {...}}) — admin only
    """

    def initial(self, request, *args, **kwargs):
        project_id = kwargs.get("project_id")
        project = (
            Project.objects.filter(id=project_id).select_related("workspace").first()
        )
        if project is None:
            raise NotFound("project not found")
        self._project = project
        self.kwargs["slug"] = project.workspace.slug
        super().initial(request, *args, **kwargs)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, project_id, slug):
        rules = resolve_config(self._project)
        return Response({"rules": rules}, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, project_id, slug):
        rules = request.data.get("rules")
        error = _validate_rules_shape(rules)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        for key, value in rules.items():
            if not State.objects.filter(
                project_id=self._project.id, name__iexact=value
            ).exists():
                return Response(
                    {"error": f"state '{value}' not found in project"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        row = StateTransitionConfig.objects.filter(
            scope="project", project_id=self._project.id
        ).first()
        if row is None:
            row = StateTransitionConfig(scope="project", project=self._project)
        row.rules = rules
        row.save()
        return Response({"rules": row.rules}, status=status.HTTP_200_OK)
