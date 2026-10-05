# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# ORM / business logic for the public-API project-page endpoints. No HTTP
# concerns — api_views.py is the thin layer on top.
#
# WHY PATCH CLEARS description_binary (the load-bearing decision of this app):
# Plane pages are collaborative documents. The live (Hocuspocus/Yjs) server
# treats `Page.description_binary` as the source of truth and REGENERATES
# description_html / description_json from it on every save
# (apps/live/src/extensions/database.ts `storeDocument`). A writer that updates
# only `description_html` therefore leaves a stale binary behind: the next time
# anyone opens the page, `fetchDocument` loads the OLD binary and the next
# store overwrites the edit — a successful-looking no-op.
#
# Upstream's own "page with HTML but no binary" paths (PageViewSet.create with
# no description_binary, PageDuplicateEndpoint which sets description_binary to
# None) rely on the other branch of `fetchDocument`: when the stored binary is
# EMPTY, live converts description_html (+ the page name, as the Yjs `title`
# fragment) into binary itself and persists binary/html/json back. So a PATCH
# here writes the new html and clears the binary + json in the same atomic
# UPDATE: the three formats can never disagree, and live rebuilds the binary
# from the html on the next open. The /convert-document live endpoint is NOT
# used on purpose — it takes no title (a regenerated Yjs `title` fragment would
# come back empty and title-sync would blank the page name) and upstream calls
# it with the "rich" schema for pages.

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from plane.bgtasks.page_transaction_task import page_transaction
from plane.db.models import Page, PageVersion, Project, ProjectMember
from plane.utils.content_validator import validate_html_content
from plane.utils.error_codes import ERROR_CODES

ROLE_GUEST = 5
# Mirrors the cap in plane.bgtasks.page_version_task.track_page_version.
PAGE_VERSION_LIMIT = 20
PATCHABLE_FIELDS = ("name", "description_html")
EMPTY_PAGE_HTML = "<p></p>"


class PageUpdateRefused(Exception):
    """The page is in a state that must not be edited over the API."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason  # a key of plane.utils.error_codes.ERROR_CODES
        self.error_code = ERROR_CODES[reason]


def resolve_project_or_404(slug, project_id):
    """Return the (non-archived) project, enforcing that <slug> owns <project_id>."""
    try:
        return Project.objects.get(workspace__slug=slug, pk=project_id, archived_at__isnull=True)
    except Project.DoesNotExist:
        raise Http404("Project does not exist in this workspace")


def visible_pages(project, user):
    """Pages of `project` the caller may see.

    Mirrors the app's PageViewSet.get_queryset: private pages (access=1) only
    for their owner, and a guest sees only their own pages unless the project
    sets guest_view_all_features. Unlike the UI list, sub-pages are included
    (each carries its `parent`) so an API consumer can address any page.
    """
    queryset = (
        Page.objects.filter(
            workspace_id=project.workspace_id,
            project_pages__project_id=project.id,
            project_pages__deleted_at__isnull=True,
        )
        .filter(Q(owned_by_id=user.id) | Q(access=Page.PUBLIC_ACCESS))
        .select_related("owned_by")
        .distinct()
    )
    is_guest = ProjectMember.objects.filter(
        project_id=project.id, member=user, role=ROLE_GUEST, is_active=True
    ).exists()
    if is_guest and not project.guest_view_all_features:
        queryset = queryset.filter(owned_by_id=user.id)
    return queryset


def get_visible_page_or_404(project, user, page_id):
    page = visible_pages(project, user).filter(pk=page_id).first()
    if page is None:
        raise Http404("Page does not exist in this project")
    return page


def serialize_page(page, include_content=False):
    data = {
        "id": str(page.id),
        "name": page.name,
        "access": page.access,
        "owned_by": str(page.owned_by_id),
        "owned_by_display_name": page.owned_by.display_name if page.owned_by_id else None,
        "parent": str(page.parent_id) if page.parent_id else None,
        "is_locked": page.is_locked,
        "is_archived": page.archived_at is not None,
        "archived_at": page.archived_at.isoformat() if page.archived_at else None,
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }
    if include_content:
        data["description_html"] = page.description_html
        data["description_stripped"] = page.description_stripped
    return data


def parse_patch(payload):
    """Validate a PATCH body. Returns ((name, description_html), error).

    Unknown keys are REJECTED rather than ignored: a PATCH that returns 200
    while silently dropping `access` or `is_locked` is exactly the failure
    mode the fork's other v1 endpoints exist to fix (docs/FORK.md).
    """
    if not isinstance(payload, dict):
        return None, "request body must be a JSON object"

    unknown = sorted(set(payload) - set(PATCHABLE_FIELDS))
    if unknown:
        return None, f"unsupported field(s): {', '.join(unknown)}; patchable fields are {', '.join(PATCHABLE_FIELDS)}"

    name = payload.get("name")
    if "name" in payload and not isinstance(name, str):
        return None, "name must be a string"

    description_html = payload.get("description_html")
    if "description_html" in payload:
        if not isinstance(description_html, str) or not description_html.strip():
            return None, f"description_html must be a non-empty string (use '{EMPTY_PAGE_HTML}' to clear a page)"
        is_valid, error, clean_html = validate_html_content(description_html)
        if not is_valid:
            return None, error
        description_html = clean_html if clean_html is not None else description_html

    if name is None and description_html is None:
        return None, "provide name and/or description_html"

    return (name, description_html), None


def _snapshot_previous_version(page, user):
    """Keep the pre-edit content restorable from the page's version history.

    The UI's own recorder (bgtasks.page_version_task.track_page_version) reads
    `page.description`, an attribute Page does not have, so it raises and logs
    on every call and records nothing; and it snapshots the NEW state. An
    API write that replaces a human-authored table must not be the one edit
    with no way back, so snapshot the OLD state synchronously, inside the
    same transaction as the write.
    """
    PageVersion.objects.create(
        page_id=page.id,
        workspace_id=page.workspace_id,
        description_json=page.description_json,
        description_html=page.description_html,
        description_binary=page.description_binary,
        description_stripped=page.description_stripped,
        owned_by_id=user.id,
        last_saved_at=timezone.now(),
        sub_pages_data={},
    )
    overflow = PageVersion.objects.filter(page_id=page.id).order_by("-last_saved_at")[PAGE_VERSION_LIMIT:]
    stale_ids = [version.id for version in overflow]
    if stale_ids:
        PageVersion.objects.filter(id__in=stale_ids).delete()


def apply_page_update(page_id, user, name=None, description_html=None):
    """Apply a validated PATCH; returns (page, changed).

    Runs in one transaction on a row lock so two API writers serialise, and
    re-checks lock/archive state INSIDE the lock (a check before it could be
    stale by the time the write lands).
    """
    with transaction.atomic():
        # of=("self",): lock the page row only, not the joined owner's user row.
        page = Page.objects.select_for_update(of=("self",)).select_related("owned_by").get(pk=page_id)

        if page.is_locked:
            raise PageUpdateRefused("PAGE_LOCKED")
        if page.archived_at is not None:
            raise PageUpdateRefused("PAGE_ARCHIVED")

        name_changed = name is not None and name != page.name
        html_changed = description_html is not None and description_html != page.description_html
        if not (name_changed or html_changed):
            return page, False

        old_html = page.description_html
        update_fields = ["description_binary", "updated_at", "updated_by"]

        if html_changed:
            _snapshot_previous_version(page, user)
            page.description_html = description_html
            # The old json no longer matches the new html; live rebuilds it.
            page.description_json = {}
            # description_stripped is derived from description_html in Page.save().
            update_fields += ["description_html", "description_json", "description_stripped"]
        if name_changed:
            page.name = name
            update_fields.append("name")

        # Any change to name or content invalidates the Yjs state (content AND
        # the `title` fragment live to be rebuilt) — see the module docstring.
        page.description_binary = None
        page.updated_by = user
        # disable_auto_set_user: BaseModel.save resolves the user from crum's
        # request user, which is anonymous under API-key auth and would NULL
        # created_by/updated_by.
        page.save(update_fields=update_fields, disable_auto_set_user=True)

        if html_changed:
            new_html = page.description_html
            transaction.on_commit(
                lambda: page_transaction.delay(
                    new_description_html=new_html,
                    old_description_html=old_html,
                    page_id=str(page_id),
                )
            )
    return page, True
