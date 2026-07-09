# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P0 — RepoProjectMap auto-seed. Repo -> Project matching is intentionally
# conservative: an exact, unambiguous name match only. Never guesses; an
# unmatched repo gets project=None (editable later via the P4 API/MCP
# surface — see plan §0 locked decisions).

import logging

from django.db.models import Q

logger = logging.getLogger("plane.github_ext")


def _iter_repos_from_payload(event_type, payload):
    if event_type == "installation":
        return payload.get("repositories") or []
    if event_type == "installation_repositories":
        return payload.get("repositories_added") or []
    return []


def _infer_project(workspace, repo_name):
    """Exact, case-insensitive match on Project.name or Project.identifier,
    scoped to the installation's workspace. Returns None (never guesses) on
    zero or multiple matches."""
    from plane.db.models import Project

    candidates = Project.objects.filter(workspace=workspace).filter(
        Q(name__iexact=repo_name) | Q(identifier__iexact=repo_name)
    )
    if candidates.count() == 1:
        return candidates.first()
    return None


def seed_repo_project_map(installation, event_type, payload):
    """Auto-seed `RepoProjectMap` for each repo attached to this
    installation event. Unmatched repos get `project=None` — surfaced, never
    silently mapped."""
    from plane.github_ext.models import RepoProjectMap

    for repo in _iter_repos_from_payload(event_type, payload):
        full_name = repo.get("full_name") or repo.get("name")
        if not full_name:
            continue

        repo_name = repo.get("name") or full_name.rsplit("/", 1)[-1]
        project = _infer_project(installation.workspace, repo_name)

        RepoProjectMap.objects.update_or_create(
            installation=installation,
            repo_full_name=full_name,
            defaults={"project": project},
        )
        if project is None:
            logger.info(
                "seed_repo_project_map: no confident project match for repo=%s "
                "(installation=%s) - left unmapped",
                full_name,
                installation.installation_id,
            )
