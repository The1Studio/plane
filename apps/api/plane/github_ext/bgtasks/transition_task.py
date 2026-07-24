# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P2 — PR-lifecycle → work-item state automation. Consumes `pull_request`
# events dispatched from bgtasks/dispatch.py (alongside P1's process_refs) and
# applies configured state transitions via the service-token internal API
# (services/state_transition.py — NEVER issue.save()).

import logging

from celery import shared_task

from plane.github_ext.parsing.closing_words import find_closing_links
from plane.github_ext.parsing.refs import extract_identifiers
from plane.github_ext.services.repo_scope import resolve_issue, resolve_mapped_project
from plane.github_ext.services.state_transition import (
    apply_transition,
    ensure_bot_membership,
    get_service_credentials,
    resolve_target_state,
)

logger = logging.getLogger("plane.github_ext")


def _resolve_installation(payload):
    from plane.github_ext.models import GithubInstallation

    gh_id = (payload.get("installation") or {}).get("id")
    if gh_id is None:
        return None
    return GithubInstallation.objects.filter(installation_id=str(gh_id)).first()


def _event_key(action, merged):
    """Map a pull_request action to a transition event key, or None for
    actions that must NOT transition (closed-unmerged, etc.).

    Returns (event_key, require_closing_word).
    """
    if action == "opened":
        return "pr_opened", False
    if action in ("ready_for_review", "review_requested"):
        return "pr_ready_for_review", False
    if action == "closed" and merged:
        # Only merges linked via a Linear closing word move the item to Done
        # (phase-P2.md): a bare merged PR is not an implicit close.
        return "pr_merged", True
    return None, False


@shared_task(
    name="plane.github_ext.bgtasks.transition_task.process_pr_transition",
    bind=True,
    max_retries=2,
)
def process_pr_transition(self, payload=None):
    """Apply the configured state transition for a pull_request event.

    Never raises on malformed/ambiguous data — every drop path (unknown
    installation, loop-guarded self-event, unmapped repo, unresolved issue,
    missing target state, missing service token) is logged and returned.
    """
    payload = payload or {}
    pr = payload.get("pull_request") or {}
    action = payload.get("action") or ""

    event_key, require_closing = _event_key(action, bool(pr.get("merged")))
    if event_key is None:
        return

    installation = _resolve_installation(payload)
    if installation is None:
        logger.info("process_pr_transition: unknown/absent installation - dropping")
        return

    # Loop guard: drop events originated by our own App bot (a transition we
    # made must never echo back into another transition). The bot's GitHub
    # login is stored on GithubInstallation.config["bot_login"].
    sender_login = (payload.get("sender") or {}).get("login")
    bot_login = (installation.config or {}).get("bot_login")
    if bot_login and sender_login and sender_login == bot_login:
        logger.info(
            "process_pr_transition: event from our bot login=%s - dropping (loop guard)",
            bot_login,
        )
        return

    repo_full_name = (payload.get("repository") or {}).get("full_name")
    if not repo_full_name:
        return
    project = resolve_mapped_project(installation, repo_full_name)
    if project is None:
        return

    text = "\n".join(
        t
        for t in (
            (pr.get("head") or {}).get("ref") or "",
            pr.get("title") or "",
            pr.get("body") or "",
        )
        if t
    )
    if require_closing:
        identifiers = {identifier for _word, identifier in find_closing_links(text)}
    else:
        identifiers = set(extract_identifiers(text))
    if not identifiers:
        return

    target_state = resolve_target_state(project, event_key)
    if target_state is None:
        logger.info(
            "process_pr_transition: no target state for event=%s in project=%s - skip",
            event_key,
            project.identifier,
        )
        return

    bot_user, service_token = get_service_credentials(installation)
    if not service_token:
        return

    # The bot must be a project member for ProjectEntityPermission to allow
    # the service-token PATCH (idempotent, once per project).
    ensure_bot_membership(bot_user, project)

    for identifier in identifiers:
        issue = resolve_issue(project, identifier)
        if issue is None:
            continue
        apply_transition(issue, target_state, service_token)
