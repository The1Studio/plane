# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork (cascade_ext) — docs/FORK.md touch-point 2. Two thin HTTP
# endpoint pairs; all logic lives in service.py so preview and apply can never
# disagree on what is eligible. No core view is edited — the default "only
# change this item" path stays the existing plain PATCH, untouched.
#
# Contract, decisions, and test matrix:
# plans/260822-cascade-complete-sub-items/phase-1-cascade-backend.md
# plans/260828-module-cascade-terminal-status/phase-1-module-cascade-backend.md

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, Module, State
from plane.utils.host import base_host

from .service import (
    MAX_MODULE_CASCADE_ITEMS,
    MODULE_STATUS_TO_STATE_GROUP,
    CascadeCapExceeded,
    apply_cascade,
    apply_module_cascade,
    collect_descendants,
    collect_module_cascade,
)

_VALID_TARGET_GROUPS = {"completed", "cancelled"}

# Hard-cap refusal body is part of the frozen endpoint contract (Phase 1 §
# Endpoint contract) — the field names and this exact error string are what
# the TypeScript client parses.
_CAP_ERROR = "cascade exceeds MAX_MODULE_CASCADE_ITEMS"


class CascadePreviewEndpoint(BaseAPIView):
    """GET .../cascade-preview/?group=<completed|cancelled>

    Read-only. Answers "what would cascade if the parent moved into `group`
    right now" — the client calls this BEFORE the parent's state actually
    changes, to decide whether to show the confirmation modal at all
    (plan Decision 3: no children, or all descendants already terminal =>
    plain state change, no prompt). Same read gate as viewing the issue
    itself — this endpoint changes nothing.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        target_group = request.GET.get("group")
        if target_group not in _VALID_TARGET_GROUPS:
            return Response(
                {"error": "group must be one of completed|cancelled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        issue = Issue.issue_objects.filter(
            pk=issue_id, project_id=project_id, workspace__slug=slug
        ).first()
        if issue is None:
            return Response(
                {"error": "issue not found"}, status=status.HTTP_404_NOT_FOUND
            )

        collected = collect_descendants(
            root_issue=issue, target_group=target_group, actor_id=request.user.id
        )
        return Response(
            {
                "target_group": target_group,
                "depth_capped": collected["depth_capped"],
                "descendants": collected["descendants"],
            },
            status=status.HTTP_200_OK,
        )


class CascadeApplyEndpoint(BaseAPIView):
    """POST .../cascade-apply/  { state_id, child_ids? }

    Applies the parent's new state plus a caller-selected subset of
    currently-eligible descendants, in one transaction. `child_ids` is a
    REQUEST, never an authorization — service.apply_cascade re-derives
    eligibility server-side and rejects anything not currently eligible.

    Gated the same as the write path this replaces for "cascade too"
    (ADMIN/MEMBER — the roles that may change an issue's state per
    IssueViewSet.partial_update).
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        state_id = request.data.get("state_id")
        if not state_id:
            return Response(
                {"error": "state_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        issue = Issue.issue_objects.filter(
            pk=issue_id, project_id=project_id, workspace__slug=slug
        ).first()
        if issue is None:
            return Response(
                {"error": "issue not found"}, status=status.HTTP_404_NOT_FOUND
            )

        state = State.objects.filter(pk=state_id, project_id=project_id).first()
        if state is None:
            return Response(
                {"error": "state not found in this project"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        child_ids = request.data.get("child_ids", None)
        if child_ids is not None and not isinstance(child_ids, list):
            return Response(
                {"error": "child_ids must be a list, null, or omitted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = apply_cascade(
            root_issue=issue,
            state=state,
            child_ids=child_ids,
            actor_id=request.user.id,
            slug=slug,
            origin=base_host(request=request, is_app=True),
        )
        return Response(result, status=status.HTTP_200_OK)


def _get_module_or_response(slug, project_id, module_id):
    """Shared lookup + guards for the module cascade endpoints.

    Returns (module, None) on success or (None, Response) with the failure —
    404 when absent, 400 when archived (M13: mirroring the core viewset's own
    refusal to write an archived module).
    """
    module = Module.objects.filter(
        pk=module_id, project_id=project_id, workspace__slug=slug
    ).first()
    if module is None:
        return None, Response(
            {"error": "module not found"}, status=status.HTTP_404_NOT_FOUND
        )
    if module.archived_at:
        return None, Response(
            {"error": "module is archived"}, status=status.HTTP_400_BAD_REQUEST
        )
    return module, None


class ModuleCascadePreviewEndpoint(BaseAPIView):
    """GET .../modules/<module_id>/cascade-preview/?status=<completed|cancelled>

    Read-only. Answers "what would cascade if this module went terminal right
    now" — the client calls this BEFORE the module's status actually changes.
    The query parameter is `status` (a MODULE status), NOT the issue
    endpoint's `group`; the two are deliberately not unified. Same read gate
    as viewing the module itself.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, module_id):
        module_status = request.GET.get("status")
        if module_status not in MODULE_STATUS_TO_STATE_GROUP:
            return Response(
                {"error": "status must be one of completed|cancelled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        module, error = _get_module_or_response(slug, project_id, module_id)
        if error is not None:
            return error

        collected = collect_module_cascade(
            module=module,
            target_group=MODULE_STATUS_TO_STATE_GROUP[module_status],
            actor_id=request.user.id,
        )
        return Response(collected, status=status.HTTP_200_OK)


class ModuleCascadeApplyEndpoint(BaseAPIView):
    """POST .../modules/<module_id>/cascade-apply/  { status, item_ids? }

    Applies the module's new status plus a caller-selected subset of
    currently-eligible items, in ONE transaction (M5). `item_ids` is a
    REQUEST, never an authorization — service.apply_module_cascade re-derives
    eligibility server-side. Over the hard cap, 400 and NOTHING is written,
    module status included (M4).

    Gated the same as the module write path it mirrors (ADMIN/MEMBER — the
    roles that may write a module per ModuleViewSet.partial_update).
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, module_id):
        module_status = request.data.get("status")
        if module_status not in MODULE_STATUS_TO_STATE_GROUP:
            return Response(
                {"error": "status must be one of completed|cancelled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        module, error = _get_module_or_response(slug, project_id, module_id)
        if error is not None:
            return error

        item_ids = request.data.get("item_ids", None)
        if item_ids is not None and not isinstance(item_ids, list):
            return Response(
                {"error": "item_ids must be a list, null, or omitted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = apply_module_cascade(
                module=module,
                status=module_status,
                item_ids=item_ids,
                actor_id=request.user.id,
                slug=slug,
                origin=base_host(request=request, is_app=True),
            )
        except CascadeCapExceeded as exc:
            return Response(
                {
                    "error": _CAP_ERROR,
                    "total_live": exc.total_live,
                    "cap": MAX_MODULE_CASCADE_ITEMS,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result, status=status.HTTP_200_OK)
