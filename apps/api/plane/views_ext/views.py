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
from plane.utils.order_queryset import order_issue_queryset
from plane.utils.paginator import GroupedOffsetPaginator, SubGroupedOffsetPaginator


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

    # group_by / sub_group_by accepted values — server field paths matching what the
    # frontend's EIssueGroupByToServerOptions already emits
    # (packages/constants/src/issue/common.ts), not UI labels. `state` (individual),
    # `cycle` and `module` are deliberately excluded (D3): they are per-project and
    # would produce ~40 near-duplicate columns across a 12-project workspace. This is
    # a decision, not an oversight — do not "fix" it to be exhaustive.
    ALLOWED_GROUP_BY_FIELDS = frozenset({"state__group", "priority", "project_id", "labels__id"})

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
        Carried across from WorkspaceViewIssuesViewSet.apply_annotations — same
        annotate() chain as the core workspace-view issue list, so the response
        exposes the same computed fields (cycle_id, link_count, attachment_count,
        sub_issues_count) that WorkspaceViewIssuesViewSet and
        WorkspaceUserProfileIssuesEndpoint both already expose.
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

    def _parse_date_range(self, request):
        """
        Parse `before` / `after` (YYYY-MM-DD) query params. Returns
        (before, after, error_response) — error_response is a ready 400 Response on
        a malformed date, never a silently-ignored bad value.
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

    def get(self, request, slug):
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

        before, after, error_response = self._parse_date_range(request)
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
        count_filter = Q(
            Q(issue_intake__status=1) | Q(issue_intake__status=-1) | Q(issue_intake__status=2) | Q(issue_intake__isnull=True),
            archived_at__isnull=True,
            is_draft=False,
        )

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
