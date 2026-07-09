# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P0 — installation bootstrap: upsert GithubInstallation from an
# `installation` / `installation_repositories` webhook payload.

import logging

logger = logging.getLogger("plane.github_ext")


def _resolve_workspace_for_installation(payload):
    """Resolve the Plane workspace bound to the GitHub integration.

    P0 ships no admin UI (backend-only MVP, plan §0). Binding a workspace to
    the GitHub App is an out-of-band admin step: create a
    `WorkspaceIntegration` row for `Integration(provider="github")` pointing
    at the target workspace (Django admin/shell). If none exists yet, the
    caller drops the event rather than guessing a workspace.
    """
    from plane.db.models import WorkspaceIntegration

    workspace_integration = (
        WorkspaceIntegration.objects.filter(integration__provider="github")
        .select_related("workspace")
        .first()
    )
    if workspace_integration is None:
        return None
    return workspace_integration.workspace


def handle_installation_event(event_type, payload):
    """Upsert `GithubInstallation` from an `installation` /
    `installation_repositories` webhook payload.

    Returns the `GithubInstallation` row, or `None` if no workspace is bound
    yet — the event is dropped (never mapped onto an arbitrary workspace).
    """
    from plane.github_ext.models import GithubInstallation

    installation_data = payload.get("installation") or {}
    installation_id = installation_data.get("id")
    if installation_id is None:
        logger.warning("handle_installation_event: payload missing installation.id")
        return None

    account = installation_data.get("account") or {}
    account_login = account.get("login", "")

    workspace = _resolve_workspace_for_installation(payload)
    if workspace is None:
        logger.warning(
            "handle_installation_event: no WorkspaceIntegration bound for "
            "Integration(provider=github) - dropping installation_id=%s "
            "until an admin connects a workspace",
            installation_id,
        )
        return None

    installation, _created = GithubInstallation.objects.update_or_create(
        installation_id=str(installation_id),
        defaults={
            "account_login": account_login,
            "workspace": workspace,
        },
    )
    return installation
