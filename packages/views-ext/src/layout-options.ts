// The1Studio fork (views-layouts)
//
// Fork-owned layout-options table for the workspace Views tab (the GLOBAL issue store).
//
// Upstream `ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions`
// (@plane/constants, packages/constants/src/issue/filter.ts) only defines `spreadsheet` and
// `list`, and its `list` entry carries no `group_by`. `@plane/*` is sealed (docs/FORK.md
// forbids editing it in place) — this table is the fork-owned replacement, covering all 5
// layouts for the Views tab specifically. See plan.md § B2.
//
// Each entry is modelled on the `profile_issues` entry in that same upstream file — also a
// workspace-level, cross-project view, so its choices are already validated for this exact
// context. See plan.md § D3 for the `group_by` set and its rationale.

import { ISSUE_DISPLAY_PROPERTIES_KEYS } from "@plane/constants";
import type { TFiltersLayoutOptions } from "@plane/constants";
import { EIssueLayoutTypes } from "@plane/types";

/**
 * D3 group-by set for grouped layouts (List, Board): State group, Priority, Project, Labels.
 *
 * Do NOT widen this to `state` / `cycle` / `module` — those are per-project fields and, in a
 * cross-project workspace view, would produce roughly one column/swimlane per project's
 * distinct state/cycle/module (~40 duplicates across a busy workspace) instead of one shared
 * grouping axis.
 */
const GLOBAL_VIEW_GROUP_BY_FIELDS = ["state_detail.group", "priority", "project", "labels"] as const;

/**
 * Layout options for every layout the Views tab can render, keyed by `EIssueLayoutTypes`
 * value (which is also the string key upstream's own layout tables use — e.g. `gantt_chart`,
 * not `gantt`). Only List, Board (Kanban) and Spreadsheet are wired to a live root today
 * (`GLOBAL_VIEW_LAYOUTS` below); Calendar and Gantt entries exist so the table is complete
 * per-layout ahead of Phases 4/5, and so `getGlobalViewQueryParamsByLayout` never has to
 * guess for a layout that isn't switcher-visible yet.
 */
export const GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS: TFiltersLayoutOptions = {
  [EIssueLayoutTypes.LIST]: {
    display_properties: ISSUE_DISPLAY_PROPERTIES_KEYS,
    display_filters: {
      group_by: [...GLOBAL_VIEW_GROUP_BY_FIELDS, null],
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
      group_by: [...GLOBAL_VIEW_GROUP_BY_FIELDS],
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
