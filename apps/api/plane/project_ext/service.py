# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# ORM / business logic for project visibility, workspace-admin project
# enumeration, and workspace-admin project-member add. No HTTP concerns —
# views.py and api_views.py are the thin layers on top.

from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef
from django.http import Http404

from plane.db.models import Project, ProjectMember, User, Workspace, WorkspaceMember

# Mirrors plane.db.models.project.Project.NETWORK_CHOICES = ((0, "Secret"), (2, "Public")).
NETWORK_SECRET = 0
NETWORK_PUBLIC = 2
VALID_NETWORKS = (NETWORK_SECRET, NETWORK_PUBLIC)

NETWORK_LABELS = {NETWORK_SECRET: "secret", NETWORK_PUBLIC: "public"}

# Mirrors plane.db.models.project.ROLE_CHOICES = ((20, "Admin"), (15, "Member"), (5, "Guest")).
ROLE_ADMIN = 20
ROLE_MEMBER = 15
ROLE_GUEST = 5
VALID_ROLES = (ROLE_ADMIN, ROLE_MEMBER, ROLE_GUEST)
ROLE_LABEL_MAP = {"admin": ROLE_ADMIN, "member": ROLE_MEMBER, "guest": ROLE_GUEST}
DEFAULT_PROJECT_MEMBER_ROLE = ROLE_MEMBER


def resolve_project_or_404(slug, project_id):
    """Return the project, enforcing that <slug> actually owns <project_id>."""
    try:
        return Project.objects.get(workspace__slug=slug, pk=project_id)
    except Project.DoesNotExist:
        raise Http404("Project does not exist in this workspace")


def resolve_workspace_or_404(slug):
    """Return the workspace, or 404 when <slug> is unknown."""
    try:
        return Workspace.objects.get(slug=slug)
    except Workspace.DoesNotExist:
        raise Http404("Workspace does not exist")


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


def list_all_projects(workspace, requesting_user_id):
    """Every project in <workspace>, private or public.

    WHY THIS EXISTS: the public-API project list
    (`GET /api/v1/workspaces/<slug>/projects/`,
    `plane.api.views.project.ProjectListCreateAPIEndpoint.get_queryset`) only
    returns projects the caller is a *project member* of, plus public
    (`network=2`) ones. A workspace ADMIN who is not a member of any private
    project therefore sees zero rows via the public API even though the web
    UI (which checks the workspace role, not project membership) shows all of
    them. This is the workspace-admin escape hatch.

    Takes the already-resolved <workspace> (not a slug) — the caller resolves
    it via resolve_workspace_or_404 in initial(), before the role gate; taking
    the object here avoids a second, redundant lookup of the same row.
    """
    projects = (
        Project.objects.filter(workspace_id=workspace.id)
        .annotate(
            is_project_member=Exists(
                ProjectMember.objects.filter(
                    project_id=OuterRef("pk"),
                    member_id=requesting_user_id,
                    is_active=True,
                )
            )
        )
        .order_by("-created_at")
    )

    results = [{**serialize(project), "is_member": project.is_project_member} for project in projects]

    return {
        "workspace_slug": workspace.slug,
        "count": len(results),
        "results": results,
    }


def parse_role(raw):
    """Coerce a request-supplied project-member role.

    Returns (role, error). `raw is None` resolves to DEFAULT_PROJECT_MEMBER_ROLE
    (role is optional on the add-member request) — everything else must be a
    valid role or an explicit error, same non-silent-default discipline as
    parse_network.
    """
    if raw is None:
        return DEFAULT_PROJECT_MEMBER_ROLE, None

    if isinstance(raw, bool):
        return None, "role must be 20, 15, or 5, not a boolean"

    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in ROLE_LABEL_MAP:
            return ROLE_LABEL_MAP[token], None
        try:
            raw = int(token)
        except ValueError:
            return None, f"invalid role {raw!r} — expected 20, 15, 5, 'admin', 'member' or 'guest'"

    if not isinstance(raw, int):
        return None, f"invalid role {raw!r} — expected 20, 15, 5, 'admin', 'member' or 'guest'"

    if raw not in VALID_ROLES:
        return None, f"invalid role {raw} — expected 20 (admin), 15 (member), or 5 (guest)"

    return raw, None


def resolve_target_user(user_id, email):
    """Resolve the add-member request's target user from user_id OR email.

    Returns (user, error). Exactly one of user_id/email is expected; a
    malformed user_id (not a valid UUID) is a 400 via ValidationError, not an
    unhandled 500.
    """
    if not user_id and not email:
        return None, "user_id or email is required"

    if user_id:
        try:
            user = User.objects.filter(pk=user_id).first()
        except (ValidationError, ValueError):
            return None, f"invalid user_id {user_id!r}"
    else:
        user = User.objects.filter(email=str(email).strip().lower()).first()

    if user is None:
        return None, "user not found"

    return user, None


def resolve_projects_or_404(slug, project_ids):
    """Return every Project for <project_ids>, enforcing that <slug> owns all
    of them. Raises Http404 (not a 400) if ANY id is unknown/unowned — the
    whole call fails rather than applying a partial update, same all-or-
    nothing intent as set_visibility_bulk, but surfaced as 404 (matching
    resolve_project_or_404's single-project convention) per this endpoint's
    contract rather than set_visibility_bulk's 400.
    """
    projects = list(Project.objects.filter(workspace__slug=slug, pk__in=project_ids))
    found = {str(p.id) for p in projects}
    missing = [str(pid) for pid in project_ids if str(pid) not in found]
    if missing:
        raise Http404(f"project_ids not found in workspace {slug}: {', '.join(missing)}")
    return projects


def _upsert_project_member(project, user, role):
    """Add — or reactivate/re-role — <user> as a member of <project>.

    A brand-new row goes through ProjectMember.objects.create() rather than
    bulk_create(), so ProjectMember.save()'s override runs — it sets
    sort_order and creates the matching ProjectUserProperty row, the same
    side effects plane.app.views.project.member.ProjectMemberViewSet.create
    reproduces by hand for its bulk_create path. This is the same row shape
    Plane's own UI creates, so the project becomes visible to the user
    through the normal project list immediately.

    Idempotent: re-adding an existing active member with the same role is a
    no-write, created=False; re-adding an inactive member (or one whose role
    changed) reactivates/updates the existing row rather than creating a
    duplicate. Returns created (bool).
    """
    member = ProjectMember.objects.filter(project=project, member=user).first()
    if member is None:
        ProjectMember.objects.create(project=project, member=user, role=role)
        return True

    if member.role != role or not member.is_active:
        member.role = role
        member.is_active = True
        member.save(update_fields=["role", "is_active"])
    return False


def add_project_members_bulk(slug, project_ids, user, role):
    """Add — or reactivate/re-role — <user> as a member of every project in
    <project_ids>, all within <slug>'s workspace.

    <project_ids> must be a non-empty list, and every id must belong to
    <slug> — Http404 otherwise (resolve_projects_or_404), whole call fails,
    no partial apply. <user> MUST already be an active member of <slug>'s
    workspace; this never silently adds them to the workspace itself (400
    otherwise). Returns (payload, error) — error is always a 400-shaped
    message; the project-ownership case raises Http404 directly instead of
    returning through this tuple.
    """
    if not project_ids:
        return None, "project_ids must be a non-empty list of project UUIDs"

    if not isinstance(project_ids, (list, tuple)):
        return None, "project_ids must be a list of project UUIDs"

    projects = resolve_projects_or_404(slug, project_ids)

    if not WorkspaceMember.objects.filter(workspace__slug=slug, member=user, is_active=True).exists():
        return None, f"{user.email or user.id} is not a member of workspace {slug}"

    results = [
        {"project_id": str(project.id), "created": _upsert_project_member(project, user, role)} for project in projects
    ]

    return {
        "user_id": str(user.id),
        "email": user.email,
        "role": role,
        "results": results,
    }, None
