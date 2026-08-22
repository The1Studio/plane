# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Workload HTTP endpoints (thin): parse + validate + permission, then defer
# to service.compute_workload / the estimate model. Mounted from core urls.py
# via an append-only include (docs/FORK.md touch-point 2).

import uuid
from datetime import date

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, Workspace

from .aggregation import ALLOWED_GRANULARITIES
from .constants import DEFAULT_MAX_DAILY_HOURS, DEFAULT_WEEK_START_DAY, DEFAULT_WORKDAYS
from .models import WorkloadEstimate, WorkloadSettings
from .rollup import RollupTooLarge, compute_rollups, is_parent, parent_issue_ids
from .serializers import WorkloadEstimateSerializer, WorkloadSettingsSerializer
from .service import (
    VALID_STATE_GROUPS,
    BulkEstimatesError,
    WorkloadTooLarge,
    bulk_estimates,
    compute_workload,
    is_guest_restricted,
    is_issue_assignee,
    validate_bulk_issue_ids,
)

_SPAN_CAPS = {"day": 92, "week": 366, "month": 730}


class _BadRequest(Exception):
    def __init__(self, message):
        self.message = message


def _split_uuids(raw):
    out = []
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if not tok or tok == "null":
            continue
        try:
            out.append(uuid.UUID(tok))
        except ValueError:
            continue
    return out


def _parse_common(request):
    granularity = request.GET.get("granularity")
    if granularity not in ALLOWED_GRANULARITIES:
        raise _BadRequest("granularity must be one of day|week|month")

    raw_from = request.GET.get("date_from")
    raw_to = request.GET.get("date_to")
    try:
        date_from = date.fromisoformat(raw_from or "")
        date_to = date.fromisoformat(raw_to or "")
    except ValueError:
        raise _BadRequest("date_from and date_to are required ISO dates (YYYY-MM-DD)")

    if date_from > date_to:
        raise _BadRequest("date_from must be <= date_to")

    inclusive_days = (date_to - date_from).days + 1
    if inclusive_days > _SPAN_CAPS[granularity]:
        raise _BadRequest(
            f"date range too large for granularity={granularity} "
            f"(max {_SPAN_CAPS[granularity]} days)"
        )

    state_groups = []
    for tok in (request.GET.get("state_group") or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok not in VALID_STATE_GROUPS:
            raise _BadRequest(f"invalid state_group: {tok}")
        state_groups.append(tok)

    return {
        "granularity": granularity,
        "date_from": date_from,
        "date_to": date_to,
        "requested_project_ids": _split_uuids(request.GET.get("project_ids")),
        "assignee_ids": _split_uuids(request.GET.get("assignee_ids")),
        "state_groups": state_groups,
    }


def _run(request, slug, route_project_id=None):
    try:
        params = _parse_common(request)
    except _BadRequest as exc:
        return Response({"error": exc.message}, status=status.HTTP_400_BAD_REQUEST)
    try:
        data = compute_workload(
            user=request.user,
            slug=slug,
            route_project_id=route_project_id,
            **params,
        )
    except WorkloadTooLarge:
        return Response(
            {"error": "Result too large — narrow by project or assignee."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(data, status=status.HTTP_200_OK)


# Shared estimate handlers — reused by both the app API (this module) and the
# public API (api_views.py), so the logic lives in exactly one place.

def estimate_get(request, slug, project_id, issue_id):
    # Flag-off guests may read an estimate only for issues assigned to them
    # (mirrors core's per-issue guest gate in app/views/issue/base.py).
    if is_guest_restricted(request.user, slug, project_id) and not is_issue_assignee(
        request.user, project_id, issue_id
    ):
        return Response(
            {"error": "You are not allowed to view this estimate"},
            status=status.HTTP_403_FORBIDDEN,
        )
    parent_flag = is_parent(issue_id)
    obj = WorkloadEstimate.objects.filter(issue_id=issue_id, project_id=project_id).first()
    data = WorkloadEstimateSerializer(obj).data if obj is not None else {"hours": None}
    data["is_parent"] = parent_flag
    if parent_flag:
        # Stored legacy value (if any) never leaks to the UI once an issue
        # has countable children — estimates live on the sub-items instead.
        data["hours"] = None
        rollups = compute_rollups(request.user, slug, [issue_id])
        data["rollup"] = rollups.get(str(issue_id))
    return Response(data, status=status.HTTP_200_OK)


def estimate_put(request, slug, project_id, issue_id):
    serializer = WorkloadEstimateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    hours = serializer.validated_data["hours"]

    issue = Issue.objects.filter(id=issue_id, project_id=project_id, workspace__slug=slug).first()
    if issue is None:
        return Response({"error": "issue not found"}, status=status.HTTP_404_NOT_FOUND)

    if is_parent(issue.id):
        return Response(
            {
                "error": "This issue has sub-items — set estimates on the sub-items instead.",
                "error_code": "PARENT_HAS_CHILDREN",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    obj, _created = WorkloadEstimate.objects.update_or_create(
        issue_id=issue.id,
        defaults={
            "hours": hours,
            "workspace_id": issue.workspace_id,
            "project_id": issue.project_id,
            "created_by": request.user,
        },
    )
    return Response(WorkloadEstimateSerializer(obj).data, status=status.HTTP_200_OK)


def estimate_delete(project_id, issue_id):
    # DELETE stays allowed on parents (cleanup) — the hard block is PUT-only.
    WorkloadEstimate.objects.filter(issue_id=issue_id, project_id=project_id).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# Shared work-settings handlers — reused by both the app API (this module)
# and the public API (api_views.py). Workspace-scoped, singleton-per-workspace
# (no id segment in the URL): GET returns the constants.py defaults when no
# row exists yet (never 404, never writes on read); PUT is update_or_create.
# There is no DELETE — a workspace always has effective settings.

def settings_get(request, slug):
    obj = WorkloadSettings.objects.filter(workspace__slug=slug).first()
    if obj is None:
        return Response(
            {
                "max_daily_hours": DEFAULT_MAX_DAILY_HOURS,
                "workdays": list(DEFAULT_WORKDAYS),
                "week_start_day": DEFAULT_WEEK_START_DAY,
            },
            status=status.HTTP_200_OK,
        )
    return Response(WorkloadSettingsSerializer(obj).data, status=status.HTTP_200_OK)


def settings_put(request, slug):
    serializer = WorkloadSettingsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    workspace = Workspace.objects.filter(slug=slug).first()
    if workspace is None:
        return Response({"error": "workspace not found"}, status=status.HTTP_404_NOT_FOUND)

    obj, _created = WorkloadSettings.objects.update_or_create(
        workspace=workspace,
        defaults={
            **serializer.validated_data,
            "created_by": request.user,
        },
    )
    return Response(WorkloadSettingsSerializer(obj).data, status=status.HTTP_200_OK)


def estimate_bulk(request, slug):
    """Shared handler for the bulk estimates endpoint.

    Parses `issue_ids` CSV from query params, delegates to
    service.bulk_estimates, and returns the result dict.
    Maps BulkEstimatesError (empty/oversize list) → 400.
    Other exceptions are not caught here and propagate to DRF's 500 handler.
    """
    raw = request.GET.get("issue_ids", "")
    ids = _split_uuids(raw)
    try:
        data = bulk_estimates(request.user, slug, ids)
    except BulkEstimatesError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(data, status=status.HTTP_200_OK)


def rollups_bulk(request, slug):
    """Shared handler for the bulk rollups endpoint.

    Authz mirrors estimate_bulk/bulk_estimates VERBATIM (same cap/empty
    validation, same project-scope + guest-restriction primitives, applied
    inside compute_rollups). Only ids that ARE parents are ever included in
    the response body — non-parent ids, and ids outside the caller's scope,
    are both simply absent (caller cannot distinguish "not a parent" from
    "not visible to you", by design — same as bulk_estimates).
    """
    raw = request.GET.get("issue_ids", "")
    ids = _split_uuids(raw)
    try:
        validate_bulk_issue_ids(ids)
    except BulkEstimatesError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    parents = parent_issue_ids(ids)
    if not parents:
        return Response({}, status=status.HTTP_200_OK)

    try:
        data = compute_rollups(request.user, slug, list(parents))
    except RollupTooLarge:
        return Response(
            {"error": "Result too large — narrow the issue_ids list."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(data, status=status.HTTP_200_OK)


class WorkloadEstimatesBulkEndpoint(BaseAPIView):
    """GET /api/workspaces/<slug>/workload-estimates/?issue_ids=a,b,c

    Returns {<issue_uuid>: <hours>} for all in-scope stored estimates.
    Missing issue ids (no estimate row) are omitted from the response.
    level="WORKSPACE" is mandatory — no project_id in the URL.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return estimate_bulk(request, slug)


class WorkloadRollupsBulkEndpoint(BaseAPIView):
    """GET /api/workspaces/<slug>/workload-rollups/?issue_ids=a,b,c

    Returns {<issue_uuid>: rollup} for ids that ARE parents (>=1 countable
    child); non-parent ids are omitted. Authz mirrors
    WorkloadEstimatesBulkEndpoint verbatim. level="WORKSPACE" is mandatory —
    no project_id in the URL.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return rollups_bulk(request, slug)


class WorkspaceWorkloadEndpoint(BaseAPIView):
    """GET /api/workspaces/<slug>/workload/ — workspace-scoped matrix."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return _run(request, slug, route_project_id=None)


class ProjectWorkloadEndpoint(BaseAPIView):
    """GET /api/workspaces/<slug>/projects/<project_id>/workload/."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        # project_id already a UUID via the <uuid:project_id> URL converter.
        return _run(request, slug, route_project_id=project_id)


class WorkloadEstimateEndpoint(BaseAPIView):
    """GET/PUT the per-issue estimate.

    /api/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/workload-estimate/
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        return estimate_get(request, slug, project_id, issue_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        return estimate_put(request, slug, project_id, issue_id)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, issue_id):
        return estimate_delete(project_id, issue_id)


class WorkloadSettingsEndpoint(BaseAPIView):
    """GET/PUT workspace-wide work configuration (max daily hours, workdays,
    week start day).

    /api/workspaces/<slug>/work-settings/

    GET returns the constants.py defaults for a workspace with no row yet
    (never 404) and is readable by ADMIN and MEMBER — non-admins need it to
    render correct week columns and the read-only cap badge (phase-0.md).
    PUT is ADMIN-only and does update_or_create; there is no DELETE — a
    workspace always has effective settings.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        return settings_get(request, slug)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        return settings_put(request, slug)
