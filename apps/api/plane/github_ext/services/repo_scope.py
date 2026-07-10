# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1/P2 shared repo -> project scope resolver. Both `write_links` (P1,
# services/link_writer.py) and `process_pr_transition` (P2,
# bgtasks/transition_task.py) need "which Plane project does this GitHub
# repo belong to" resolved strictly via `RepoProjectMap` — never guessed,
# never cross-project. Extracted here so the two features share one lookup
# instead of duplicating it (phase-P2.md step "Resolve the linked issue(s)
# via the same RepoProjectMap scope logic as P1 ... do NOT duplicate").

import logging
import re

logger = logging.getLogger("plane.github_ext")

_IDENTIFIER_SPLIT_RE = re.compile(r"^([A-Z]+)-(\d+)$")


def resolve_issue(project, identifier):
    """Resolve a Plane `Issue` from a `PROJ-123` identifier, strictly within
    `project`. The `[A-Z]+` prefix MUST equal `project.identifier` — an
    identifier for a different project resolves to `None` (never cross-mapped,
    phase-P1.md risk table "cross-project mis-link"). `None` when the prefix
    mismatches or no issue with that sequence_id exists.
    """
    from plane.db.models import Issue

    match = _IDENTIFIER_SPLIT_RE.match(identifier or "")
    if not match:
        return None
    prefix, seq = match.group(1), match.group(2)
    if prefix != project.identifier:
        return None
    return Issue.objects.filter(project_id=project.id, sequence_id=int(seq)).first()


def resolve_mapped_project(installation, repo_full_name):
    """Return the `Project` a GitHub repo is mapped to via `RepoProjectMap`,
    or `None` if the repo is unmapped or has no confident project match.

    Never guesses (mirrors services/repo_map.py's "never guess" convention)
    — callers must treat `None` as "drop this event, do no work".
    """
    from plane.github_ext.models import RepoProjectMap

    try:
        repo_map = RepoProjectMap.objects.select_related("project").get(
            installation=installation, repo_full_name=repo_full_name
        )
    except RepoProjectMap.DoesNotExist:
        logger.info(
            "resolve_mapped_project: repo=%s is unmapped (installation=%s) - no project",
            repo_full_name,
            installation.installation_id,
        )
        return None

    if repo_map.project is None:
        logger.info(
            "resolve_mapped_project: repo=%s has no confident project match - no project",
            repo_full_name,
        )
        return None

    return repo_map.project
