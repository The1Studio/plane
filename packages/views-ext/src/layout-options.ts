// The1Studio fork (views-layouts, profile-layouts)
//
// Fork-owned layout-options tables for two workspace-level, cross-project issue stores:
// the workspace Views tab (GLOBAL store) and the "Your work" profile pages (PROFILE store,
// `/:workspaceSlug/profile/:userId/{assigned,created,subscribed}`).
//
// Upstream `ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions` (@plane/constants,
// packages/constants/src/issue/filter.ts) only defines `spreadsheet` and `list`, and its
// `list` entry carries no `group_by`. `ISSUE_DISPLAY_FILTERS_BY_PAGE.profile_issues.layoutOptions`
// only defines `list` and `kanban`. `@plane/*` is sealed (docs/FORK.md forbids editing it in
// place) — these tables are the fork-owned replacements, each covering all 5 layouts for its
// tab. See plan.md § B2 (GLOBAL) and the profile-layouts follow-up (PROFILE).
//
// GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS was modelled on the upstream `profile_issues` entry (also a
// workspace-level, cross-project view, so its choices were already validated for this exact
// context — plan.md § D3). Now that PROFILE gets its own fork-owned table, the two share every
// field: same `group_by` set, same `order_by`, same `extra_options`. That is not a coincidence
// to paper over with an alias — both stores are workspace-level and cross-project, and D3's
// rationale (below) applies identically to both. `buildWorkspaceLevelViewLayoutOptions` is the
// single place that structure is declared; GLOBAL and PROFILE each call it and can diverge
// later (e.g. a different `group_by` set for one of them) by editing only their own call site.

import { ISSUE_DISPLAY_PROPERTIES_KEYS } from "@plane/constants";
import type { TFiltersLayoutOptions } from "@plane/constants";
import { EIssueLayoutTypes } from "@plane/types";
import type { TIssueGroupByOptions } from "@plane/types";

/**
 * D3 group-by set for grouped layouts (List, Board): State group, Priority, Project, Labels.
 * Shared by every workspace-level, cross-project store built via
 * `buildWorkspaceLevelViewLayoutOptions` below (currently GLOBAL and PROFILE).
 *
 * Do NOT widen this to `state` / `cycle` / `module` — those are per-project fields and, in a
 * cross-project view, would produce roughly one column/swimlane per project's distinct
 * state/cycle/module (~40 duplicates across a busy workspace) instead of one shared grouping
 * axis.
 */
const WORKSPACE_LEVEL_VIEW_GROUP_BY_FIELDS: readonly TIssueGroupByOptions[] = [
  "state_detail.group",
  "priority",
  "project",
  "labels",
] as const;

/**
 * Builds a full 5-layout `TFiltersLayoutOptions` table for a workspace-level, cross-project
 * issue store, parameterized by its grouped-layout (List, Board) `group_by` field set — the one
 * axis that could legitimately differ between such stores. Every other choice (display
 * properties, order_by, extra_options) is identical across GLOBAL and PROFILE today, so it is
 * NOT parameterized; if a genuine per-store difference shows up later, add a parameter for that
 * specific field rather than forking the whole table back into two literals.
 *
 * Keyed by `EIssueLayoutTypes` value (which is also the string key upstream's own layout tables
 * use — e.g. `gantt_chart`, not `gantt`). Only List, Board (Kanban) and Spreadsheet are wired to
 * a live root today for either store; Calendar and Gantt entries exist so each table is complete
 * per-layout ahead of further phases, and so the query-param builders never have to guess for a
 * layout that isn't switcher-visible yet.
 */
function buildWorkspaceLevelViewLayoutOptions(
  groupByFields: readonly TIssueGroupByOptions[]
): TFiltersLayoutOptions {
  return {
    [EIssueLayoutTypes.LIST]: {
      display_properties: ISSUE_DISPLAY_PROPERTIES_KEYS,
      display_filters: {
        group_by: [...groupByFields, null],
        order_by: ["sort_order", "-created_at", "-updated_at", "start_date", "-priority"],
        type: ["active", "backlog"],
      },
      extra_options: {
        access: true,
        values: ["show_empty_groups", "sub_issue"],
      },
    },
    [EIssueLayoutTypes.KANBAN]: {
      display_properties: ISSUE_DISPLAY_PROPERTIES_KEYS,
      display_filters: {
        group_by: [...groupByFields],
        order_by: ["sort_order", "-created_at", "-updated_at", "start_date", "-priority"],
        type: ["active", "backlog"],
      },
      extra_options: {
        access: true,
        values: ["show_empty_groups"],
      },
    },
    [EIssueLayoutTypes.SPREADSHEET]: {
      display_properties: ISSUE_DISPLAY_PROPERTIES_KEYS,
      display_filters: {
        order_by: ["sort_order", "-created_at", "-updated_at", "start_date", "-priority"],
        type: ["active", "backlog"],
      },
      extra_options: {
        access: true,
        values: ["sub_issue"],
      },
    },
    [EIssueLayoutTypes.CALENDAR]: {
      display_properties: ["key", "issue_type"],
      display_filters: {
        type: ["active", "backlog"],
      },
      extra_options: {
        access: true,
        values: ["sub_issue"],
      },
    },
    [EIssueLayoutTypes.GANTT]: {
      display_properties: ["key", "issue_type"],
      display_filters: {
        order_by: ["sort_order", "-created_at", "-updated_at", "start_date", "-priority"],
        type: ["active", "backlog"],
      },
      extra_options: {
        access: true,
        values: ["sub_issue"],
      },
    },
  };
}

/**
 * Layout options for every layout the workspace Views tab can render. See
 * `buildWorkspaceLevelViewLayoutOptions` above for what is and isn't parameterized.
 */
export const GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS: TFiltersLayoutOptions = buildWorkspaceLevelViewLayoutOptions(
  WORKSPACE_LEVEL_VIEW_GROUP_BY_FIELDS
);

/**
 * Layout options for every layout the "Your work" profile pages (assigned / created /
 * subscribed) can render. Preserves the exact `group_by` set upstream's own `profile_issues`
 * entry used for List/Board — see `WORKSPACE_LEVEL_VIEW_GROUP_BY_FIELDS` above; this table does
 * not widen it.
 */
export const PROFILE_VIEW_ISSUE_LAYOUT_OPTIONS: TFiltersLayoutOptions = buildWorkspaceLevelViewLayoutOptions(
  WORKSPACE_LEVEL_VIEW_GROUP_BY_FIELDS
);

/**
 * The single place layout availability for the Views tab switcher is decided. Phases 4
 * (Calendar) and 5 (Timeline) append to this array as those layouts get a live root — the
 * switcher component itself is never touched to add a layout.
 */
export const GLOBAL_VIEW_LAYOUTS: EIssueLayoutTypes[] = [
  EIssueLayoutTypes.LIST,
  EIssueLayoutTypes.KANBAN,
  EIssueLayoutTypes.CALENDAR,
  EIssueLayoutTypes.SPREADSHEET,
  EIssueLayoutTypes.GANTT,
];

/**
 * The single place layout availability for the profile pages' switcher is decided, mirroring
 * `GLOBAL_VIEW_LAYOUTS` above.
 */
export const PROFILE_VIEW_LAYOUTS: EIssueLayoutTypes[] = [
  EIssueLayoutTypes.LIST,
  EIssueLayoutTypes.KANBAN,
  EIssueLayoutTypes.CALENDAR,
  EIssueLayoutTypes.SPREADSHEET,
  EIssueLayoutTypes.GANTT,
];
