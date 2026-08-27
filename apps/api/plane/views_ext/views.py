# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork (views-layouts) — docs/FORK.md D2. A new Django app rather than
# extending `plane.app.views.view.base.WorkspaceViewIssuesViewSet` in place, which
# `plane-classify-path.cjs` classifies as `core` (editing it is an isolation-audit
# violation and a guaranteed rebase conflict outside the 7 documented touch-points).
#
# This endpoint combines two existing endpoints rather than inventing a third
# pattern — see plans/260817-1616-views-layout-switcher/phase-1-backend-views-ext.md:
#   - WorkspaceViewIssuesViewSet (plane.app.views.view.base) supplies the queryset
#     base, the django-filter + legacy filtering, and `_get_project_permission_filters`
#     (guest-role visibility — carried across verbatim, do not weaken).
#   - WorkspaceUserProfileIssuesEndpoint (plane.app.views.workspace.user) supplies the
#     group_by / sub_group_by branching and the paginate() call shapes.
#
# Contract (SSOT): plans/260817-1616-views-layout-switcher/plan.md § "Contract —
# pinned before any parallel work". Do not restate or diverge from it here.
#
# GroupedWorkspaceUserProfileIssuesEndpoint below is a sibling addition, not covered
# by that plan (it predates the profile-page layout-switcher work). Its own contract
# — response shape, permission model — is pinned inline on the class docstring,
# mirroring plane.app.views.workspace.user.WorkspaceUserProfileIssuesEndpoint
# (~lines 98-249) verbatim rather than the Views-tab contract above; the two core
# endpoints it and GroupedWorkspaceViewIssuesEndpoint mirror have different
# permission models (see each class's docstring) and must not be conflated.

import copy
from datetime import datetime

# Django imports
from django.db.models import F, Func, OuterRef, Prefetch, Q, Subquery

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import WorkspaceViewerPermission
from plane.app.views.base import BaseAPIView
from plane.workload_cache.cache import (
    CachedJSONResponse,
    get_cached_bytes,
    render_json,
    set_cached,
)
from plane.workload_cache.keys import SURFACE_VIEWSEXT
from plane.db.models import (
    CycleIssue,
    FileAsset,
    Issue,
    IssueAssignee,
    IssueLabel,
    ModuleIssue,
    IssueLink,
)
from plane.utils.filters import ComplexFilterBackend, IssueFilterSet
from plane.utils.grouper import (
    issue_group_values,
    issue_on_results,
    issue_queryset_grouper,
)
from plane.utils.issue_filters import issue_filters
from plane.utils.issue_search import search_issues
from plane.utils.order_queryset import order_issue_queryset
from plane.utils.paginator import GroupedOffsetPaginator, SubGroupedOffsetPaginator

# group_by / sub_group_by accepted values — the complete set of server field paths
# EIssueGroupByToServerOptions can emit (packages/constants/src/issue/common.ts).
#
# This list validates what the SERVER can group by. It is deliberately NOT a restatement
# of which options the workspace-level UI chooses to OFFER — that curation (D3: prefer
# state__group / priority / project_id / labels__id, since per-project fields produce
# near-duplicate columns across a 40-project workspace) belongs in the fork-owned
# layout-options table in packages/views-ext, which drives the dropdown.
#
# Conflating the two shipped a real bug: a display filter persisted from the Work Items
# tab (which does offer plain `state`) sends group_by=state_id, and Calendar always sends
# group_by=target_date. Neither was in the old four-value set, so both 400'd on every
# request — List and Board never rendered, and Calendar silently fell back to ungrouped.
# Core's own endpoints pass group_by straight to issue_queryset_grouper with no allowlist
# at all; this set still catches typos and injection without rejecting valid UI values.
GROUP_BY_FIELDS = frozenset(
    {
        "state_id",
        "state__group",
        "priority",
        "labels__id",
        "assignees__id",
        "cycle_id",
        "issue_module__module_id",
        "target_date",
        "project_id",
        "created_by",
    }
)

# Group counts exclude non-terminal intake issues and drafts — verbatim from
# WorkspaceUserProfileIssuesEndpoint's paginate() call shapes. Shared at module scope
# since both grouped endpoints below use the identical Q object.
NON_DRAFT_COUNT_FILTER = Q(
    Q(issue_intake__status=1) | Q(issue_intake__status=-1) | Q(issue_intake__status=2) | Q(issue_intake__isnull=True),
    archived_at__isnull=True,
    is_draft=False,
)


def parse_date_range(request):
    """
    Parse `before` / `after` (YYYY-MM-DD) query params. Returns
    (before, after, error_response) — error_response is a ready 400 Response on a
    malformed date, never a silently-ignored bad value. Shared by every endpoint in
    this module that accepts the Calendar date-range window.
    """
    before = request.GET.get("before") or None
    after = request.GET.get("after") or None

    for label, value in (("before", before), ("after", after)):
        if value is None:
            continue
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return (
                None,
                None,
                Response(
                    {"error": f"Invalid {label} value. Expected format: YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                ),
            )

    return before, after, None


def apply_issue_annotations(issues):
    """
    Shared annotate()/prefetch_related() chain — same computed fields
    (cycle_id, link_count, attachment_count, sub_issues_count) and the same
    Prefetch-based assignee/label/module prefetches every grouped endpoint in this
    module needs. Extracted so GroupedWorkspaceViewIssuesEndpoint and
    GroupedWorkspaceUserProfileIssuesEndpoint cannot drift apart on this.
    """
    return (
        issues.annotate(
            cycle_id=Subquery(
                CycleIssue.objects.filter(issue=OuterRef("id"), deleted_at__isnull=True).values("cycle_id")[:1]
            )
        )
        .annotate(
            link_count=IssueLink.objects.filter(issue=OuterRef("id"))
            .order_by()
            .annotate(count=Func(F("id"), function="Count"))
            .values("count")
        )
        .annotate(
            attachment_count=FileAsset.objects.filter(
                issue_id=OuterRef("id"),
                entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            )
            .order_by()
            .annotate(count=Func(F("id"), function="Count"))
            .values("count")
        )
        .annotate(
            sub_issues_count=Issue.issue_objects.filter(parent=OuterRef("id"))
            .order_by()
            .annotate(count=Func(F("id"), function="Count"))
            .values("count")
        )
        .prefetch_related(Prefetch("issue_assignee", queryset=IssueAssignee.objects.all()))
        .prefetch_related(Prefetch("label_issue", queryset=IssueLabel.objects.all()))
        .prefetch_related(Prefetch("issue_module", queryset=ModuleIssue.objects.all()))
    )


def apply_issue_search(queryset, request):
    """The1Studio fork (views-search) — narrow by work-item name / number / project identifier.

    An empty or absent `search` is NOT a filter: it returns the queryset untouched. Never
    let a blank box become a hidden exclusion.
    """
    query = request.query_params.get("search", "").strip()
    if not query:
        return queryset
    return search_issues(query, queryset)


class GroupedWorkspaceViewIssuesEndpoint(BaseAPIView):
    """
    GET /api/views-ext/workspaces/<slug>/issues/

    Workspace-wide, cross-project issue list for the Views tab layout switcher
    (List / Board / Calendar / Spreadsheet / Timeline), with optional server-side
    `group_by` / `sub_group_by` grouping and a `before` / `after` target-date range.
    The core `/api/workspaces/<slug>/issues/` endpoint (WorkspaceViewIssuesViewSet)
    has no grouping support — this is the fork-owned addition (D2).
    """

    permission_classes = [WorkspaceViewerPermission]

    filter_backends = (ComplexFilterBackend,)
    filterset_class = IssueFilterSet

    # Kept as a class attr (alias of the module-level GROUP_BY_FIELDS) so existing
    # references to `self.ALLOWED_GROUP_BY_FIELDS` / call sites outside this module
    # keep working unchanged.
    ALLOWED_GROUP_BY_FIELDS = GROUP_BY_FIELDS

    def _get_project_permission_filters(self):
        """
        Get common project permission filters for guest users and role-based access
        control. Returns a Q object for filtering issues based on user role and
        project settings.

        Carried across VERBATIM from WorkspaceViewIssuesViewSet
        (plane.app.views.view.base) — this is what keeps a guest without
        `guest_view_all_features` from seeing issues they did not create. Do not
        "simplify" this.
        """
        return Q(
            Q(
                project__project_projectmember__role=5,
                project__guest_view_all_features=True,
            )
            | Q(
                project__project_projectmember__role=5,
                project__guest_view_all_features=False,
                created_by=self.request.user,
            )
            |
            # For other roles (role > 5), show all issues
            Q(project__project_projectmember__role__gt=5),
            project__project_projectmember__member=self.request.user,
            project__project_projectmember__is_active=True,
        )

    def apply_annotations(self, issues):
        """
        Thin alias of the module-level `apply_issue_annotations` — kept as an
        instance method so existing external references to
        `GroupedWorkspaceViewIssuesEndpoint().apply_annotations` keep working
        unchanged. See the module-level function's docstring for what it does.
        """
        return apply_issue_annotations(issues)

    def get(self, request, slug):
        """Cache wrapper. All logic lives in _get_uncached.

        Wrapping the whole method rather than its three paginate() return paths
        keeps one cache-write site instead of three, so a future branch added to
        _get_uncached cannot silently skip caching.

        `search` is ephemeral free text (CLAUDE.md). It changes the response, so
        it cannot simply be dropped from the key — but it is high-cardinality
        and every entry would be read once, so the cache is skipped entirely
        while it is set. Empty/absent search returns everything and is the
        common, cacheable case.
        """
        cacheable = not (request.GET.get("search") or "").strip()
        if cacheable:
            cached = get_cached_bytes(SURFACE_VIEWSEXT, slug, request.user.id, request.GET)
            if cached is not None:
                return CachedJSONResponse(cached, status=status.HTTP_200_OK)

        response = self._get_uncached(request, slug)

        # 200 only. A cached 400 would outlive the condition that produced it.
        if cacheable and response.status_code == status.HTTP_200_OK:
            body = render_json(response.data)
            set_cached(SURFACE_VIEWSEXT, slug, request.user.id, request.GET, body)
            return CachedJSONResponse(body, status=status.HTTP_200_OK)
        return response

    def _get_uncached(self, request, slug):
        group_by = request.GET.get("group_by") or None
        sub_group_by = request.GET.get("sub_group_by") or None

        if group_by is not None and group_by not in self.ALLOWED_GROUP_BY_FIELDS:
            return Response(
                {
                    "error": "Invalid group_by value. Accepted values: "
                    f"{', '.join(sorted(self.ALLOWED_GROUP_BY_FIELDS))}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if sub_group_by is not None:
            if sub_group_by not in self.ALLOWED_GROUP_BY_FIELDS:
                return Response(
                    {
                        "error": "Invalid sub_group_by value. Accepted values: "
                        f"{', '.join(sorted(self.ALLOWED_GROUP_BY_FIELDS))}"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if group_by is None:
                return Response(
                    {"error": "sub_group_by requires group_by to also be set"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if group_by == sub_group_by:
                return Response(
                    {"error": "Group by and sub group by cannot have same parameters"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        before, after, error_response = parse_date_range(request)
        if error_response is not None:
            return error_response

        issue_queryset = Issue.issue_objects.filter(workspace__slug=slug)

        # Apply filtering from the filterset (ComplexFilterBackend + IssueFilterSet)
        issue_queryset = self.filter_queryset(issue_queryset)

        order_by_param = request.GET.get("order_by", "-created_at")

        # Apply legacy filters
        filters = issue_filters(request.query_params, "GET")
        issue_queryset = issue_queryset.filter(**filters)

        # Calendar date-range window (D2 contract; Phase 4 is the first consumer,
        # implemented now per the pinned contract)
        if after:
            issue_queryset = issue_queryset.filter(target_date__gte=after)
        if before:
            issue_queryset = issue_queryset.filter(target_date__lte=before)

        # Guest-role visibility — verbatim, see _get_project_permission_filters
        issue_queryset = issue_queryset.filter(self._get_project_permission_filters())

        # The1Studio fork (views-search) — after permission scoping, before pagination.
        # Applied to the queryset the total count is derived from (deepcopied below so
        # total_issue_queryset.count() reflects the searched set, not the unsearched one).
        issue_queryset = apply_issue_search(issue_queryset, request)

        # Total count queryset (pre-annotation, cheap — mirrors
        # WorkspaceViewIssuesViewSet.list)
        total_issue_queryset = copy.deepcopy(issue_queryset).only("id")

        # Apply annotations to the issue queryset
        issue_queryset = self.apply_annotations(issue_queryset)

        # Grouping annotations (assignee_ids / label_ids / module_ids)
        issue_queryset = issue_queryset_grouper(queryset=issue_queryset, group_by=group_by, sub_group_by=sub_group_by)

        issue_queryset, order_by_param = order_issue_queryset(
            issue_queryset=issue_queryset, order_by_param=order_by_param
        )

        # Group counts exclude non-terminal intake issues and drafts — verbatim from
        # WorkspaceUserProfileIssuesEndpoint's paginate() call shapes.
        count_filter = NON_DRAFT_COUNT_FILTER

        if group_by:
            if sub_group_by:
                return self.paginate(
                    request=request,
                    order_by=order_by_param,
                    queryset=issue_queryset,
                    total_count_queryset=total_issue_queryset,
                    on_results=lambda issues: issue_on_results(
                        group_by=group_by, issues=issues, sub_group_by=sub_group_by
                    ),
                    paginator_cls=SubGroupedOffsetPaginator,
                    group_by_fields=issue_group_values(
                        field=group_by, slug=slug, filters=filters, queryset=total_issue_queryset
                    ),
                    sub_group_by_fields=issue_group_values(
                        field=sub_group_by, slug=slug, filters=filters, queryset=total_issue_queryset
                    ),
                    group_by_field_name=group_by,
                    sub_group_by_field_name=sub_group_by,
                    count_filter=count_filter,
                )

            return self.paginate(
                request=request,
                order_by=order_by_param,
                queryset=issue_queryset,
                total_count_queryset=total_issue_queryset,
                on_results=lambda issues: issue_on_results(group_by=group_by, issues=issues, sub_group_by=sub_group_by),
                paginator_cls=GroupedOffsetPaginator,
                group_by_fields=issue_group_values(
                    field=group_by, slug=slug, filters=filters, queryset=total_issue_queryset
                ),
                group_by_field_name=group_by,
                count_filter=count_filter,
            )

        return self.paginate(
            order_by=order_by_param,
            request=request,
            queryset=issue_queryset,
            total_count_queryset=total_issue_queryset,
            on_results=lambda issues: issue_on_results(group_by=group_by, issues=issues, sub_group_by=sub_group_by),
        )


class GroupedWorkspaceUserProfileIssuesEndpoint(BaseAPIView):
    """
    GET /api/views-ext/workspaces/<slug>/user-issues/<uuid:user_id>/

    Per-user "Your work" profile issue list (assigned / created / subscribed) for the
    profile-page layout switcher (List / Board / Calendar / Spreadsheet / Timeline),
    with optional server-side `group_by` / `sub_group_by` grouping and a `before` /
    `after` target-date range. The core `/api/workspaces/<slug>/user-issues/<user_id>/`
    endpoint (WorkspaceUserProfileIssuesEndpoint, plane.app.views.workspace.user,
    ~lines 98-249) has neither — this is the fork-owned addition, same D2 rationale as
    GroupedWorkspaceViewIssuesEndpoint above.

    Response shape is byte-identical to WorkspaceUserProfileIssuesEndpoint's own
    (both go through the same paginate()/issue_on_results() machinery) — do not
    "improve" it.

    `type` — carried across from the way the frontend's ProfileIssues store already
    scopes each of the three profile tabs (apps/web/core/store/issue/profile/
    issue.store.ts), via the *existing* `assignees` / `created_by` / `subscriber`
    legacy filter params (plane.utils.issue_filters) rather than a bespoke selector:
    core's WorkspaceUserProfileIssuesEndpoint has no `?type=` param at all — its
    candidate pool is unconditionally the union of all three relations, and the
    frontend narrows to one tab by passing e.g. `assignees=<user_id>` as an ordinary
    filter. `type` here is an additional, optional convenience on top of that same
    mechanism: when given, it narrows the candidate pool server-side to exactly one
    relation up front (cheaper than relying on the legacy-filter narrowing alone);
    when omitted, the candidate pool matches core's own default — the union of all
    three — so an unfiltered request here returns the same rows as core. The
    `assignees` / `created_by` / `subscriber` params keep working unchanged either
    way, since they still flow through `issue_filters()` below.
    """

    permission_classes = [WorkspaceViewerPermission]

    filter_backends = (ComplexFilterBackend,)
    filterset_class = IssueFilterSet

    # `type` accepted values -> the ORM relation identifying "this issue belongs to
    # this profile view for this user_id", carried verbatim from
    # WorkspaceUserProfileIssuesEndpoint.get()'s candidate-pool Q clauses
    # (app/views/workspace/user.py:139-147).
    ALLOWED_PROFILE_TYPES = frozenset({"assigned", "created", "subscribed"})

    def _profile_type_filter(self, profile_type, user_id):
        if profile_type == "assigned":
            return Q(assignees__in=[user_id])
        if profile_type == "created":
            return Q(created_by_id=user_id)
        if profile_type == "subscribed":
            return Q(issue_subscribers__subscriber_id=user_id)
        # No type given — union of all three, matching core's unconditional pool.
        return (
            Q(assignees__in=[user_id]) | Q(created_by_id=user_id) | Q(issue_subscribers__subscriber_id=user_id)
        )

    def get(self, request, slug, user_id):
        group_by = request.GET.get("group_by") or None
        sub_group_by = request.GET.get("sub_group_by") or None
        profile_type = request.GET.get("type") or None

        if profile_type is not None and profile_type not in self.ALLOWED_PROFILE_TYPES:
            return Response(
                {
                    "error": "Invalid type value. Accepted values: "
                    f"{', '.join(sorted(self.ALLOWED_PROFILE_TYPES))}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if group_by is not None and group_by not in GROUP_BY_FIELDS:
            return Response(
                {"error": f"Invalid group_by value. Accepted values: {', '.join(sorted(GROUP_BY_FIELDS))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if sub_group_by is not None:
            if sub_group_by not in GROUP_BY_FIELDS:
                return Response(
                    {"error": f"Invalid sub_group_by value. Accepted values: {', '.join(sorted(GROUP_BY_FIELDS))}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if group_by is None:
                return Response(
                    {"error": "sub_group_by requires group_by to also be set"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if group_by == sub_group_by:
                return Response(
                    {"error": "Group by and sub group by cannot have same parameters"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        before, after, error_response = parse_date_range(request)
        if error_response is not None:
            return error_response

        # Candidate pool + permission scoping — carried across VERBATIM from
        # WorkspaceUserProfileIssuesEndpoint.get() (app/views/workspace/user.py:
        # 139-147), only the type_filter is new (see class docstring). Deliberately
        # NOT `_get_project_permission_filters()` (the guest-role-aware filter used by
        # GroupedWorkspaceViewIssuesEndpoint above) — core's profile endpoint never
        # applies that here either, because results are already scoped to issues
        # related to `user_id`, not a full project issue list; requester only needs
        # to be an active member of the containing project.
        type_filter = self._profile_type_filter(profile_type, user_id)
        issue_queryset = Issue.issue_objects.filter(
            id__in=Issue.issue_objects.filter(type_filter, workspace__slug=slug).values_list("id", flat=True),
            workspace__slug=slug,
            project__project_projectmember__member=request.user,
            project__project_projectmember__is_active=True,
        )

        # Apply filtering from the filterset (ComplexFilterBackend + IssueFilterSet)
        issue_queryset = self.filter_queryset(issue_queryset)

        order_by_param = request.GET.get("order_by", "-created_at")

        # Apply legacy filters — this is also how the frontend's ProfileIssues store
        # already narrows to a single tab today (assignees= / created_by= /
        # subscriber=), see class docstring.
        filters = issue_filters(request.query_params, "GET")
        issue_queryset = issue_queryset.filter(**filters)

        # Calendar date-range window — the feature this endpoint exists to add; core
        # has no equivalent.
        if after:
            issue_queryset = issue_queryset.filter(target_date__gte=after)
        if before:
            issue_queryset = issue_queryset.filter(target_date__lte=before)

        # Total count queryset (pre-annotation, cheap — mirrors
        # GroupedWorkspaceViewIssuesEndpoint.get())
        total_issue_queryset = copy.deepcopy(issue_queryset).only("id")

        # Apply annotations to the issue queryset
        issue_queryset = apply_issue_annotations(issue_queryset)

        # Grouping annotations (assignee_ids / label_ids / module_ids)
        issue_queryset = issue_queryset_grouper(queryset=issue_queryset, group_by=group_by, sub_group_by=sub_group_by)

        issue_queryset, order_by_param = order_issue_queryset(
            issue_queryset=issue_queryset, order_by_param=order_by_param
        )

        count_filter = NON_DRAFT_COUNT_FILTER

        if group_by:
            if sub_group_by:
                return self.paginate(
                    request=request,
                    order_by=order_by_param,
                    queryset=issue_queryset,
                    total_count_queryset=total_issue_queryset,
                    on_results=lambda issues: issue_on_results(
                        group_by=group_by, issues=issues, sub_group_by=sub_group_by
                    ),
                    paginator_cls=SubGroupedOffsetPaginator,
                    group_by_fields=issue_group_values(
                        field=group_by, slug=slug, filters=filters, queryset=total_issue_queryset
                    ),
                    sub_group_by_fields=issue_group_values(
                        field=sub_group_by, slug=slug, filters=filters, queryset=total_issue_queryset
                    ),
                    group_by_field_name=group_by,
                    sub_group_by_field_name=sub_group_by,
                    count_filter=count_filter,
                )

            return self.paginate(
                request=request,
                order_by=order_by_param,
                queryset=issue_queryset,
                total_count_queryset=total_issue_queryset,
                on_results=lambda issues: issue_on_results(group_by=group_by, issues=issues, sub_group_by=sub_group_by),
                paginator_cls=GroupedOffsetPaginator,
                group_by_fields=issue_group_values(
                    field=group_by, slug=slug, filters=filters, queryset=total_issue_queryset
                ),
                group_by_field_name=group_by,
                count_filter=count_filter,
            )

        return self.paginate(
            order_by=order_by_param,
            request=request,
            queryset=issue_queryset,
            total_count_queryset=total_issue_queryset,
            on_results=lambda issues: issue_on_results(group_by=group_by, issues=issues, sub_group_by=sub_group_by),
        )
