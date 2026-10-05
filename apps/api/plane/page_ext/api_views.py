# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Public-API (/api/v1/) project-page endpoints — API-key authenticated, for MCP
# / SDK / external consumers. Core's v1 API has no page route at all.
#
# Authorization reuses the app's own ProjectPagePermission (the class the
# session-authenticated PageViewSet uses), so the API can never see or touch
# anything the UI would not: the caller must be an ACTIVE PROJECT MEMBER (a
# workspace admin who is not in the project is refused — add them first via
# project_ext's project-members endpoint), PATCH needs Admin/Member, and a
# private page (access=1) is reachable only by its owner (403, even for admins).

from django.http import Http404
from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView  # APIKeyAuthentication
from plane.app.permissions import ProjectPagePermission

from .service import (
    PageUpdateRefused,
    apply_page_update,
    get_visible_page_or_404,
    parse_patch,
    resolve_project_or_404,
    serialize_page,
    visible_pages,
)

# Locked -> 423 Locked; archived -> 409 Conflict. Both bodies carry the same
# numeric error_code the app's description endpoint returns (PAGE_LOCKED /
# PAGE_ARCHIVED) so a client can branch on it.
_REFUSAL_STATUS = {
    "PAGE_LOCKED": status.HTTP_423_LOCKED,
    "PAGE_ARCHIVED": status.HTTP_409_CONFLICT,
}


def _not_found(exc):
    """404 body in the {"error": ...} shape every other API error here uses.

    DRF renders a bare Http404 as {"detail": ...}; clients (the MCP server's
    _send helper) read "error". The messages also differ from the custom 404
    handler's "Page not found." — the body of an UNROUTED path — so a client
    can tell "this server has no page endpoints" from "that page is not here".
    """
    return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)


class PageListAPIEndpoint(BaseAPIView):
    """GET /api/v1/workspaces/<slug>/projects/<project_id>/pages/

    Every page of the project the caller may see (id, name, access, owned_by,
    parent, is_locked, is_archived/archived_at, created_at, updated_at) — no
    page bodies; fetch one page for its content. Archived pages are listed
    and flagged. <slug> must own <project_id> (404 otherwise).
    """

    permission_classes = [ProjectPagePermission]

    def get(self, request, slug, project_id):
        try:
            project = resolve_project_or_404(slug, project_id)
        except Http404 as exc:
            return _not_found(exc)
        pages = visible_pages(project, request.user).order_by("-created_at")
        return Response([serialize_page(page) for page in pages], status=status.HTTP_200_OK)


class PageDetailAPIEndpoint(BaseAPIView):
    """GET/PATCH /api/v1/workspaces/<slug>/projects/<project_id>/pages/<page_id>/

    GET   — the page including description_html and description_stripped (plain text).
    PATCH — body {"name"?: str, "description_html"?: str}, at least one. Unknown
            keys are rejected (400). Refused with 423 on a locked page and 409 on
            an archived one. The write keeps description_html, description_stripped
            and the collaborative-editor binary consistent — see service.py.
    """

    permission_classes = [ProjectPagePermission]

    def get(self, request, slug, project_id, page_id):
        try:
            project = resolve_project_or_404(slug, project_id)
            page = get_visible_page_or_404(project, request.user, page_id)
        except Http404 as exc:
            return _not_found(exc)
        return Response(serialize_page(page, include_content=True), status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id, page_id):
        # 404 before any write if the page is not in this project / not visible.
        try:
            project = resolve_project_or_404(slug, project_id)
            get_visible_page_or_404(project, request.user, page_id)
        except Http404 as exc:
            return _not_found(exc)

        parsed, error = parse_patch(request.data)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        name, description_html = parsed

        try:
            page, changed = apply_page_update(page_id, request.user, name=name, description_html=description_html)
        except PageUpdateRefused as refusal:
            return Response(
                {"error_code": refusal.error_code, "error_message": refusal.reason, "error": refusal.reason},
                status=_REFUSAL_STATUS[refusal.reason],
            )

        payload = serialize_page(page, include_content=True)
        payload["changed"] = changed
        # True when the Yjs binary was invalidated: the live server rebuilds it
        # from description_html (+ name) the next time the page is opened.
        payload["description_binary_cleared"] = changed
        return Response(payload, status=status.HTTP_200_OK)
