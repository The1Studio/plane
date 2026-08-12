# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# ORM / business logic for project visibility. No HTTP concerns — views.py and
# api_views.py are the thin layers on top.

from django.http import Http404

from plane.db.models import Project

# Mirrors plane.db.models.project.Project.NETWORK_CHOICES = ((0, "Secret"), (2, "Public")).
NETWORK_SECRET = 0
NETWORK_PUBLIC = 2
VALID_NETWORKS = (NETWORK_SECRET, NETWORK_PUBLIC)

NETWORK_LABELS = {NETWORK_SECRET: "secret", NETWORK_PUBLIC: "public"}


def resolve_project_or_404(slug, project_id):
    """Return the project, enforcing that <slug> actually owns <project_id>."""
    try:
        return Project.objects.get(workspace__slug=slug, pk=project_id)
    except Project.DoesNotExist:
        raise Http404("Project does not exist in this workspace")


def parse_network(raw):
    """Coerce a request-supplied network value.

    Returns (network, error). Accepts the int/str form of a valid choice, or the
    human labels "secret"/"private" and "public". Rejects everything else rather
    than silently defaulting — the core serializer's silent drop of this field is
    the exact bug this app exists to fix, so we never repeat it here.
    """
    if raw is None:
        return None, "network is required (0 = secret/private, 2 = public)"

    if isinstance(raw, bool):
        return None, "network must be 0 or 2, not a boolean"

    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in ("secret", "private"):
            return NETWORK_SECRET, None
        if token == "public":
            return NETWORK_PUBLIC, None
        try:
            raw = int(token)
        except ValueError:
            return None, f"invalid network {raw!r} — expected 0, 2, 'secret' or 'public'"

    if not isinstance(raw, int):
        return None, f"invalid network {raw!r} — expected 0, 2, 'secret' or 'public'"

    if raw not in VALID_NETWORKS:
        return None, f"invalid network {raw} — expected 0 (secret) or 2 (public)"

    return raw, None


def serialize(project):
    return {
        "id": str(project.id),
        "name": project.name,
        "identifier": project.identifier,
        "network": project.network,
        "visibility": NETWORK_LABELS.get(project.network, "unknown"),
    }


def set_visibility(project, network):
    """Set one project's visibility. Returns the serialized project."""
    if project.network != network:
        project.network = network
        project.save(update_fields=["network"])
    return serialize(project)


def set_visibility_bulk(slug, project_ids, network):
    """Set visibility on many projects in one statement.

    Every id must resolve inside <slug>; a single unknown id fails the whole call
    rather than silently applying a partial update.
    Returns (payload, error).
    """
    if not project_ids:
        return None, "project_ids must be a non-empty list of project UUIDs"

    if not isinstance(project_ids, (list, tuple)):
        return None, "project_ids must be a list of project UUIDs"

    projects = Project.objects.filter(workspace__slug=slug, pk__in=project_ids)
    found = {str(p.id) for p in projects}
    missing = [str(pid) for pid in project_ids if str(pid) not in found]
    if missing:
        return None, f"project_ids not found in workspace {slug}: {', '.join(missing)}"

    updated = Project.objects.filter(workspace__slug=slug, pk__in=project_ids).exclude(network=network).update(
        network=network
    )

    return {
        "network": network,
        "visibility": NETWORK_LABELS.get(network, "unknown"),
        "requested": len(project_ids),
        "updated": updated,
        "unchanged": len(project_ids) - updated,
    }, None
