# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Opt-in gate helpers (SP2 P1 / decision A2).
# Every AI entry point must call check_workspace_enabled() before
# egressing any data to Anthropic or the BGE sidecar.

import logging

from rest_framework import status
from rest_framework.response import Response

from plane.ai_ext.cost_tracker import CostCeilingExceeded, CostTracker
from plane.ai_ext.models import AiWorkspaceConfig

logger = logging.getLogger("plane.ai_ext")


class AiGateError(Exception):
    """Raised when a workspace is not permitted to use AI features."""

    def __init__(self, message: str, http_status: int = status.HTTP_403_FORBIDDEN):
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def check_workspace_enabled(workspace_id: str) -> AiWorkspaceConfig:
    """Return the config if AI is enabled; raise AiGateError otherwise.

    Lazy-creates the config row so this is always NPE-safe.
    """
    config, _ = AiWorkspaceConfig.get_or_create_for(workspace_id)
    if not config.enabled:
        raise AiGateError(
            "AI features are not enabled for this workspace. "
            "A workspace admin must opt in and acknowledge the data-flow document."
        )
    return config


def check_cost_ceiling(workspace_id: str, ceiling_usd: float) -> None:
    """Raise AiGateError if the workspace is over its monthly spend ceiling."""
    try:
        CostTracker(workspace_id).check_ceiling(ceiling_usd)
    except CostCeilingExceeded as exc:
        raise AiGateError(str(exc), http_status=status.HTTP_429_TOO_MANY_REQUESTS)


def gate_or_403(workspace_id: str) -> Response | None:
    """View-level gate: return a 403 Response on failure, None on success.

    Usage in a view:
        err = gate_or_403(workspace_id)
        if err:
            return err
    """
    try:
        config = check_workspace_enabled(workspace_id)
        check_cost_ceiling(workspace_id, config.monthly_usd_ceiling)
        return None
    except AiGateError as exc:
        return Response({"error": exc.message}, status=exc.http_status)


def gate_or_raise(workspace_id: str) -> AiWorkspaceConfig:
    """Task-level gate: raise AiGateError on failure (Celery tasks use this).

    Returns the config so callers can read ceiling etc.
    """
    config = check_workspace_enabled(workspace_id)
    check_cost_ceiling(workspace_id, config.monthly_usd_ceiling)
    return config
