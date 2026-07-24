# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1 — dev-workflow link parsing. Consumes a `push` / `pull_request` payload
# dispatched from bgtasks/dispatch.py route_event (P0 left these as a
# no-op), extracts Plane identifiers from the branch ref / PR
# head-ref+title+body / commit messages, and hands each GitHub object off to
# services/link_writer.write_links for scope resolution + persistence.
#
# Called as a plain synchronous function from route_event (not via a second
# `.apply_async()` broker round-trip) - route_event is already running
# inside a Celery task enqueued once from the webhook view's fast-ack
# (webhook/views.py); a second hop through the broker buys nothing here and
# would require CELERY_TASK_ALWAYS_EAGER for tests to observe results
# synchronously. This mirrors the P0 installation-handling pattern
# (handle_installation_event / seed_repo_project_map are plain calls too -
# see dispatch.py). It is still declared as a `@shared_task` (name, bind,
# max_retries) for task-registry consistency and so a future phase can
# freely switch to `.apply_async()` without touching call sites' signature.

import logging

from celery import shared_task

logger = logging.getLogger("plane.github_ext")

_SUPPORTED_EVENTS = ("push", "pull_request")


def _branch_name(ref):
    prefix = "refs/heads/"
    if ref and ref.startswith(prefix):
        return ref[len(prefix) :]
    return ref or ""


def _branch_url(repo_full_name, branch_name):
    return f"https://github.com/{repo_full_name}/tree/{branch_name}"


def _commit_url(repo_full_name, sha):
    return f"https://github.com/{repo_full_name}/commit/{sha}"


def _resolve_installation(payload):
    from plane.github_ext.models import GithubInstallation

    installation_data = payload.get("installation") or {}
    installation_gh_id = installation_data.get("id")
    if installation_gh_id is None:
        logger.warning("process_refs: payload missing installation.id")
        return None

    try:
        return GithubInstallation.objects.get(installation_id=str(installation_gh_id))
    except GithubInstallation.DoesNotExist:
        logger.warning(
            "process_refs: unknown installation_id=%s - not bootstrapped yet, dropping",
            installation_gh_id,
        )
        return None


def _process_push(installation, repo_full_name, payload):
    from plane.github_ext.parsing.refs import extract_identifiers
    from plane.github_ext.services.link_writer import write_links

    ref = payload.get("ref") or ""
    branch_name = _branch_name(ref)
    if branch_name:
        write_links(
            installation=installation,
            repo_full_name=repo_full_name,
            link_type="branch",
            external_id=branch_name,
            url=_branch_url(repo_full_name, branch_name),
            text_sources=[branch_name],
        )

    # Dedup identifiers across ALL commits in this push BEFORE writing - a
    # single push can carry 100+ commits, and without this, one identifier
    # mentioned repeatedly would get one "commit" link row per commit sha
    # (phase-P1.md risk table: "commit-message spam"). Each identifier is
    # linked to exactly the first commit that mentions it.
    seen_identifiers = set()
    for commit in payload.get("commits") or []:
        message = commit.get("message") or ""
        new_identifiers = [
            identifier
            for identifier in extract_identifiers(message)
            if identifier not in seen_identifiers
        ]
        if not new_identifiers:
            continue
        seen_identifiers.update(new_identifiers)

        sha = commit.get("id") or ""
        url = commit.get("url") or _commit_url(repo_full_name, sha)
        write_links(
            installation=installation,
            repo_full_name=repo_full_name,
            link_type="commit",
            external_id=sha,
            url=url,
            text_sources=[message],
            closing_flags=True,
            only_identifiers=new_identifiers,
        )


def _process_pull_request(installation, repo_full_name, payload):
    from plane.github_ext.services.link_writer import write_links

    pr = payload.get("pull_request") or {}
    number = pr.get("number")
    if number is None:
        logger.warning("process_refs: pull_request payload missing number")
        return

    head_ref = (pr.get("head") or {}).get("ref") or ""
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    url = pr.get("html_url") or f"https://github.com/{repo_full_name}/pull/{number}"

    write_links(
        installation=installation,
        repo_full_name=repo_full_name,
        link_type="pr",
        external_id=str(number),
        url=url,
        text_sources=[head_ref, title, body],
        closing_flags=True,
    )


@shared_task(
    name="plane.github_ext.bgtasks.link_task.process_refs",
    bind=True,
    max_retries=2,
)
def process_refs(self, event_type, payload=None):
    """Parse Plane identifiers out of a dispatched `push` / `pull_request`
    payload and write WorkItemGithubLink + mirrored IssueLink rows.

    Never raises on malformed/ambiguous webhook data - every failure mode
    (unknown installation, missing repo, unmapped repo, unresolved
    identifier) is logged and dropped, matching services/installation.py and
    services/repo_map.py's "never guess" convention.
    """
    payload = payload or {}
    if event_type not in _SUPPORTED_EVENTS:
        logger.debug("process_refs: unsupported event_type=%s - no-op", event_type)
        return

    installation = _resolve_installation(payload)
    if installation is None:
        return

    repository = payload.get("repository") or {}
    repo_full_name = repository.get("full_name")
    if not repo_full_name:
        logger.warning(
            "process_refs: payload missing repository.full_name (event=%s)", event_type
        )
        return

    if event_type == "push":
        _process_push(installation, repo_full_name, payload)
    else:
        _process_pull_request(installation, repo_full_name, payload)
