# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1 — link resolution + write. Given a GitHub object (branch / PR / commit)
# and the raw text associated with it, resolve which Plane Issue(s) it
# references — strictly scoped to the repo's `RepoProjectMap.project`, never
# guessed, never cross-project (phase-P1.md risk table: "cross-project
# mis-link") — and persist:
#
#   1. WorkItemGithubLink (fork) — idempotent via the
#      unique_together(issue, link_type, external_id) constraint (models.py).
#   2. IssueLink (core)    — a DISPLAY MIRROR so the reference renders in
#      Plane's existing Links panel with zero frontend code
#      (phase-P1.md step 5).
#
# Decision (phase-P1.md step 5): the core IssueLink row is created directly
# via the ORM, NOT through IssueLinkViewSet (which needs a request/actor).
# This is a read-only display artifact, not a state-changing work-item
# mutation — no IssueActivity / notification is expected for a link row, so
# the "raw ORM write skips activity/notify/webhook" trap (see phase-P2.md
# "trap #4", which P2's service-token transition exists to avoid) does NOT
# apply here. Both writes happen inside the Celery task path and are
# idempotent so webhook redelivery never duplicates a row.

import logging
import re

from plane.github_ext.parsing.closing_words import find_closing_links
from plane.github_ext.parsing.refs import extract_identifiers

logger = logging.getLogger("plane.github_ext")

_IDENTIFIER_SPLIT_RE = re.compile(r"^([A-Z]+)-(\d+)$")


def write_links(
    installation,
    repo_full_name,
    link_type,
    external_id,
    url,
    text_sources,
    closing_flags=False,
    only_identifiers=None,
):
    """Resolve + write WorkItemGithubLink (+ mirrored IssueLink) rows for
    every Plane identifier found in `text_sources`.

    Args:
        installation: `GithubInstallation` the event belongs to.
        repo_full_name: `"owner/repo"` — looked up against `RepoProjectMap`.
        link_type: one of WorkItemGithubLink.LINK_TYPE_CHOICES ("branch",
            "pr", "commit" in P1).
        external_id: the GitHub-side identity of this link (branch name /
            PR number / commit sha) — part of the idempotency key.
        url: the GitHub URL to store on both the link row and its mirror.
        text_sources: iterable of raw strings to scan for identifiers
            (branch name / PR head-ref+title+body / commit message).
        closing_flags: when True, also scan `text_sources` for Linear-style
            closing words (close/fix/resolve/complete/implement, any tense)
            immediately preceding an identifier and stash the flag on
            WorkItemGithubLink.metadata (consumed by P2's merged-to-Done
            wiring).
        only_identifiers: optional allowlist restricting which extracted
            identifiers are actually written. Used by
            bgtasks/link_task.py to dedup identifiers across a
            multi-commit push (risk table: "commit-message spam") without
            re-implementing extraction there.

    Returns:
        list[WorkItemGithubLink] — rows created-or-matched (mainly useful
        for tests; empty when the repo is unmapped, unresolved, or no
        identifier survives resolution).
    """
    from plane.db.models import Issue, IssueLink

    from plane.github_ext.models import WorkItemGithubLink
    from plane.github_ext.services.repo_scope import resolve_mapped_project

    # Repo -> project scope resolution is shared with P2's transition_task
    # (services/repo_scope.py) — never duplicated, never guessed.
    project = resolve_mapped_project(installation, repo_full_name)
    if project is None:
        logger.info(
            "write_links: repo=%s has no mapped project (installation=%s) - dropping %s link "
            "(external_id=%s), no guess",
            repo_full_name,
            installation.installation_id,
            link_type,
            external_id,
        )
        return []

    combined_text = "\n".join(text for text in text_sources if text)
    identifiers = extract_identifiers(combined_text)
    if only_identifiers is not None:
        allowed = set(only_identifiers)
        identifiers = [identifier for identifier in identifiers if identifier in allowed]
    if not identifiers:
        return []

    # find_closing_links yields (word, identifier) tuples; index BY identifier
    # (a bare dict(...) would key by word and break the .get(identifier) lookup).
    closing_words = (
        {identifier: word for word, identifier in find_closing_links(combined_text)}
        if closing_flags
        else {}
    )

    created_links = []
    for identifier in identifiers:
        match = _IDENTIFIER_SPLIT_RE.match(identifier)
        if not match:  # pragma: no cover - extract_identifiers guarantees this shape
            continue
        prefix, seq = match.group(1), match.group(2)

        if prefix != project.identifier:
            # The `[A-Z]+` prefix must match the mapped project's identifier
            # exactly — never resolve into a different project's sequence_id
            # space (phase-P1.md risk table: "cross-project mis-link").
            logger.info(
                "write_links: identifier=%s prefix does not match mapped project=%s "
                "(repo=%s) - skipping, never cross-mapped",
                identifier,
                project.identifier,
                repo_full_name,
            )
            continue

        issue = Issue.objects.filter(project_id=project.id, sequence_id=int(seq)).first()
        if issue is None:
            logger.info(
                "write_links: no issue with sequence_id=%s in project=%s for identifier=%s "
                "- skipping",
                seq,
                project.identifier,
                identifier,
            )
            continue

        metadata = {"identifier": identifier}
        closing_word = closing_words.get(identifier)
        if closing_word:
            metadata["closing_word"] = closing_word

        link, created = WorkItemGithubLink.objects.get_or_create(
            issue=issue,
            link_type=link_type,
            external_id=external_id,
            defaults={"project": project, "url": url, "metadata": metadata},
        )
        if not created and closing_word and link.metadata.get("closing_word") != closing_word:
            # Redelivery of an edited PR (title/body changed to add a
            # closing word) keeps the flag fresh without creating a second
            # row - the unique constraint is the write path's idempotency
            # guarantee, not a freeze on metadata.
            link.metadata = {**link.metadata, "closing_word": closing_word}
            link.save(update_fields=["metadata"])

        # MIRROR (display only - see module docstring): create the core
        # IssueLink row directly. Guarded on (issue, url) so redelivery of
        # the same event never duplicates the mirror.
        IssueLink.objects.get_or_create(
            issue_id=issue.id,
            url=url,
            defaults={
                "project_id": project.id,
                "title": f"GitHub {link_type}: {external_id}",
                "metadata": metadata,
            },
        )

        created_links.append(link)

    return created_links
