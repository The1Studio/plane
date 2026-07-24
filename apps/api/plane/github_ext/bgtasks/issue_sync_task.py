# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P3 — bidirectional issue/comment sync tasks.
#
# INBOUND  (`issues` / `issue_comment` webhooks -> Plane) is wired: dispatch.py
#          routes both event types here, mirroring the P1/P2 pattern of a
#          direct synchronous call from `route_event` (see bgtasks/link_task.py
#          module docstring for why that is not `.apply_async()`).
#
# OUTBOUND (Plane -> GitHub) ships as callable tasks with a complete
#          installation-token flow and its own reflection guard, but is NOT
#          auto-triggered by this PR. Wiring it needs a `post_save` receiver in
#          github_ext/signals.py (a P0-owned file, outside this phase's file
#          ownership) AND an opt-in config flag — enabling a push on every
#          work-item save before that flag exists would mirror unrelated Plane
#          edits into GitHub. Documented as deliberate scope in the P3 report.
#
# Every drop path is logged and returns; these tasks never raise on malformed
# or ambiguous data (same contract as P2's process_pr_transition).

import logging

from celery import shared_task

from plane.github_ext.services.issue_sync import (
    EXTERNAL_SOURCE,
    SOURCE_GITHUB,
    SOURCE_PLANE,
    build_external_id,
    create_work_item,
    create_work_item_comment,
    find_mirror,
    find_mirror_for_issue,
    github_content_hash,
    html_to_body,
    is_bot_event,
    is_reflection,
    map_github_issue,
    mint_installation_token,
    patch_github_issue,
    plane_content_hash,
    resolve_state_for_github_state,
    should_push_comment,
    stamp_provenance,
    update_work_item,
    upsert_mirror,
)
from plane.github_ext.services.repo_scope import resolve_mapped_project
from plane.github_ext.services.state_transition import (
    ensure_bot_membership,
    get_service_credentials,
)

logger = logging.getLogger("plane.github_ext")

# GitHub issue actions that carry content we mirror. `deleted`/`transferred`
# are deliberately unhandled: Plane has no safe automatic response to a remote
# delete (risk row "field-mapping drift" -> unmapped, skip + log).
_ISSUE_ACTIONS = ("opened", "edited", "reopened", "closed")
_COMMENT_ACTIONS = ("created", "edited")

# The only actions that carry a state change, and the GitHub issue state they
# imply. `opened`/`edited` deliberately absent — see `_sync_issue`.
_STATE_ACTIONS = {"closed": "closed", "reopened": "open"}


def _resolve_installation(payload):
    from plane.github_ext.models import GithubInstallation

    gh_id = (payload.get("installation") or {}).get("id")
    if gh_id is None:
        return None
    return GithubInstallation.objects.filter(installation_id=str(gh_id)).first()


def _resolve_scope(payload):
    """(installation, project, repo_full_name) for an inbound event, or a
    triple of Nones when the event must be dropped."""
    installation = _resolve_installation(payload)
    if installation is None:
        logger.info("issue_sync: unknown/absent installation - dropping")
        return None, None, None

    # Echo guard (a): our own bot's writes must never round-trip back in.
    if is_bot_event(installation, payload):
        logger.info("issue_sync: event from our own bot login - dropping (loop guard)")
        return None, None, None

    repo_full_name = (payload.get("repository") or {}).get("full_name")
    if not repo_full_name:
        return None, None, None

    project = resolve_mapped_project(installation, repo_full_name)
    if project is None:
        return None, None, None

    return installation, project, repo_full_name


# ---------------------------------------------------------------------------
# INBOUND — GitHub issue -> Plane work item
# ---------------------------------------------------------------------------


def _sync_issue(payload):
    action = payload.get("action") or ""
    if action not in _ISSUE_ACTIONS:
        logger.debug("issue_sync: unhandled issues action=%s - skipping", action)
        return None

    gh_issue = payload.get("issue") or {}
    number = gh_issue.get("number")
    if number is None:
        return None
    if gh_issue.get("pull_request"):
        # A PR also surfaces as an issue object; PRs belong to P1/P2.
        return None

    installation, project, repo_full_name = _resolve_scope(payload)
    if project is None:
        return None

    external_id = build_external_id(repo_full_name, number)
    incoming_hash = github_content_hash(gh_issue.get("title"), gh_issue.get("body"))
    mirror = find_mirror(project, external_id)

    # Echo guard (b): GitHub is replaying content we ourselves last pushed.
    if mirror is not None and is_reflection(mirror.metadata, SOURCE_PLANE, incoming_hash):
        logger.info(
            "issue_sync: %s is a reflection of our own outbound write - dropping",
            external_id,
        )
        return None

    bot_user, service_token = get_service_credentials(installation)
    if not service_token:
        return None
    ensure_bot_membership(bot_user, project)

    fields = map_github_issue(gh_issue)
    # State is only touched by the two actions that MEAN a state change. An
    # `edited`/`opened` event must never reset a state a Plane user picked.
    if action in _STATE_ACTIONS:
        target_state = resolve_state_for_github_state(project, _STATE_ACTIONS[action])
        if target_state is not None:
            fields["state"] = str(target_state.id)
        else:
            logger.info(
                "issue_sync: project=%s has no state for github action=%s - syncing content only",
                project.identifier,
                action,
            )

    if mirror is None or mirror.issue is None:
        issue = create_work_item(project, service_token, fields, external_id)
        if issue is None:
            return None
        mirror = upsert_mirror(issue, project, external_id, gh_issue.get("html_url") or "")
    else:
        issue = mirror.issue
        if update_work_item(issue, service_token, fields) != 200:
            return None
        issue.refresh_from_db()

    stamp_provenance(
        mirror,
        source=SOURCE_GITHUB,
        external_id=external_id,
        github_hash=incoming_hash,
        plane_hash=plane_content_hash(issue.name, issue.description_html),
        extra={"github_issue_id": gh_issue.get("id"), "repo": repo_full_name},
    )
    return mirror


# ---------------------------------------------------------------------------
# INBOUND — GitHub comment -> Plane work-item comment
# ---------------------------------------------------------------------------


def _sync_comment(payload):
    action = payload.get("action") or ""
    if action not in _COMMENT_ACTIONS:
        logger.debug("issue_sync: unhandled issue_comment action=%s - skipping", action)
        return None

    gh_issue = payload.get("issue") or {}
    gh_comment = payload.get("comment") or {}
    number = gh_issue.get("number")
    comment_id = gh_comment.get("id")
    if number is None or comment_id is None:
        return None
    if gh_issue.get("pull_request"):
        # PR review chatter is not work-item conversation.
        return None

    installation, project, repo_full_name = _resolve_scope(payload)
    if project is None:
        return None

    mirror = find_mirror(project, build_external_id(repo_full_name, number))
    if mirror is None or mirror.issue is None:
        logger.info(
            "issue_sync: comment on unmirrored issue %s#%s - skipping",
            repo_full_name,
            number,
        )
        return None

    from plane.db.models import IssueComment

    external_comment_id = str(comment_id)
    existing = IssueComment.objects.filter(
        issue_id=mirror.issue_id,
        external_source=EXTERNAL_SOURCE,
        external_id=external_comment_id,
    ).first()
    if existing is not None:
        # Redelivery (or an `edited` we do not rewrite): never duplicate.
        logger.debug("issue_sync: comment %s already mirrored - skipping", external_comment_id)
        return existing

    _bot_user, service_token = get_service_credentials(installation)
    if not service_token:
        return None

    from plane.github_ext.services.issue_sync import body_to_html

    return create_work_item_comment(
        mirror.issue,
        service_token,
        body_to_html(gh_comment.get("body")),
        external_comment_id,
    )


@shared_task(
    name="plane.github_ext.bgtasks.issue_sync_task.process_issue_sync",
    bind=True,
    max_retries=2,
)
def process_issue_sync(self, event_type, payload=None):
    """Entry point for inbound `issues` / `issue_comment` deliveries."""
    payload = payload or {}
    if event_type == "issues":
        return _sync_issue(payload)
    if event_type == "issue_comment":
        return _sync_comment(payload)
    logger.debug("process_issue_sync: unhandled event_type=%s", event_type)
    return None


# ---------------------------------------------------------------------------
# OUTBOUND — Plane -> GitHub (implemented, not auto-triggered; see docstring)
# ---------------------------------------------------------------------------


@shared_task(
    name="plane.github_ext.bgtasks.issue_sync_task.push_work_item",
    bind=True,
    max_retries=2,
)
def push_work_item(self, issue_id):
    """Push a mirrored Plane work item's content to its GitHub issue.

    Only mirrored work items are eligible — P3 never CREATES a GitHub issue
    from Plane (that would need repo/labels/assignee policy the plan does not
    define). Returns the GitHub HTTP status code, or None on any drop path.
    """
    from plane.db.models import Issue

    from plane.github_ext.models import GithubInstallation

    issue = Issue.objects.filter(pk=issue_id).select_related("workspace").first()
    if issue is None:
        return None

    mirror = find_mirror_for_issue(issue)
    if mirror is None:
        return None

    metadata = mirror.metadata or {}
    repo_full_name = metadata.get("repo")
    external_id = metadata.get("external_id") or mirror.external_id
    if not repo_full_name or "#" not in (external_id or ""):
        logger.info("push_work_item: mirror %s has no repo/number provenance - skipping", mirror.id)
        return None
    number = external_id.rsplit("#", 1)[1]

    current_plane_hash = plane_content_hash(issue.name, issue.description_html)

    # Echo guard (b), outbound direction: the Plane content is byte-identical
    # to what we last pulled FROM GitHub, so pushing it back is a reflection.
    if is_reflection(metadata, SOURCE_GITHUB, current_plane_hash):
        logger.info("push_work_item: issue=%s unchanged since inbound sync - dropping (loop guard)", issue.id)
        return None

    installation = (
        GithubInstallation.objects.filter(workspace_id=issue.workspace_id).order_by("created_at").first()
    )
    if installation is None:
        return None

    # Fresh token per call — never cached, never persisted, never logged.
    token = mint_installation_token(installation)
    if not token:
        return None

    body = html_to_body(issue.description_html)
    status_code = patch_github_issue(token, repo_full_name, number, issue.name, body)
    if status_code != 200:
        return status_code

    stamp_provenance(
        mirror,
        source=SOURCE_PLANE,
        external_id=external_id,
        github_hash=github_content_hash(issue.name, body),
        plane_hash=current_plane_hash,
        extra={"repo": repo_full_name},
    )
    return status_code


@shared_task(
    name="plane.github_ext.bgtasks.issue_sync_task.push_comment",
    bind=True,
    max_retries=2,
)
def push_comment(self, comment_id):
    """Push a Plane-authored comment to the mirrored GitHub issue.

    Drops any comment that came FROM GitHub (`external_source="github"`) —
    the comment-side reflection guard.
    """
    import requests

    from plane.db.models import IssueComment

    from plane.github_ext.models import GithubInstallation
    from plane.github_ext.services.issue_sync import (
        GITHUB_ACCEPT,
        GITHUB_API_ROOT,
        GITHUB_API_VERSION,
    )

    comment = IssueComment.objects.filter(pk=comment_id).select_related("issue").first()
    if comment is None:
        return None

    if not should_push_comment(comment):
        logger.info("push_comment: comment=%s originated on GitHub - dropping (loop guard)", comment.id)
        return None

    mirror = find_mirror_for_issue(comment.issue)
    if mirror is None:
        return None

    metadata = mirror.metadata or {}
    repo_full_name = metadata.get("repo")
    external_id = metadata.get("external_id") or mirror.external_id
    if not repo_full_name or "#" not in (external_id or ""):
        return None
    number = external_id.rsplit("#", 1)[1]

    installation = (
        GithubInstallation.objects.filter(workspace_id=comment.issue.workspace_id).order_by("created_at").first()
    )
    if installation is None:
        return None

    token = mint_installation_token(installation)
    if not token:
        return None

    try:
        response = requests.post(
            f"{GITHUB_API_ROOT}/repos/{repo_full_name}/issues/{number}/comments",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": GITHUB_ACCEPT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            json={"body": html_to_body(comment.comment_html)},
            timeout=30,
        )
    except Exception:
        logger.warning("push_comment: request failed for %s#%s", repo_full_name, number)
        return None

    if response.status_code != 201:
        logger.warning("push_comment: %s#%s HTTP %s", repo_full_name, number, response.status_code)
    return response.status_code
