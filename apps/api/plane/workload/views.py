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
from plane.db.models import Issue

from .aggregation import ALLOWED_GRANULARITIES
from .models import WorkloadEstimate
from .serializers import WorkloadEstimateSerializer
from .service import VALID_STATE_GROUPS, WorkloadTooLarge, compute_workload

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


class WorkspaceWorkloadEndpoint(BaseAPIView):
    """GET /api/workspaces/<slug>/workload/ — workspace-scoped matrix."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        return _run(request, slug, route_project_id=None)


class ProjectWorkloadEndpoint(BaseAPIView):
    """GET /api/workspaces/<slug>/projects/<project_id>/workload/."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        # project_id already a UUID via the <uuid:project_id> URL converter.
        return _run(request, slug, route_project_id=project_id)


class WorkloadEstimateEndpoint(BaseAPIView):
    """GET/PUT the per-issue estimate.

    /api/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/workload-estimate/
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, issue_id):
        obj = WorkloadEstimate.objects.filter(
            issue_id=issue_id, project_id=project_id
        ).first()
        if obj is None:
            return Response({"hours": None}, status=status.HTTP_200_OK)
        return Response(WorkloadEstimateSerializer(obj).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        serializer = WorkloadEstimateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hours = serializer.validated_data["hours"]

        issue = Issue.objects.filter(
            id=issue_id, project_id=project_id, workspace__slug=slug
        ).first()
        if issue is None:
            return Response(
                {"error": "issue not found"}, status=status.HTTP_404_NOT_FOUND
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
        return Response(
            WorkloadEstimateSerializer(obj).data, status=status.HTTP_200_OK
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, issue_id):
        WorkloadEstimate.objects.filter(
            issue_id=issue_id, project_id=project_id
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
