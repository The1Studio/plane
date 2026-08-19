import React from "react";
import { observer } from "mobx-react";
import { STATE_GROUPS } from "@plane/constants";
import type { TWorkSettings } from "@plane/types";
import { joinUrlPath } from "@plane/utils";

import { wlt } from "./i18n";
import type { IWorkloadStore } from "./store";

// ── Types ─────────────────────────────────────────────────────────────────────

export type WorkloadToolbarProps = {
  store: IWorkloadStore;
  workspaceSlug: string;
  /** Whether the current viewer is a workspace admin — gates the "Manage" link in the settings readout. */
  isAdmin?: boolean;
  /**
   * Workspace-wide work settings, rendered as a read-only readout ("Max Nh/week
   * · workdays · week starts Day"). `undefined` renders nothing — the host
   * fetches this via the app's `useWorkSettings()` hook, since this package
   * cannot import app hooks (context-agnostic, same inversion as `isAdmin`).
   */
  workSettings?: TWorkSettings;
  /**
   * App-injected filter controls. This package cannot import from `apps/web`
   * (its deps are @plane/propel, @plane/constants, @plane/types), so the host
   * renders Plane's own store-bound dropdowns and passes them down — the same
   * inversion already used for `isAdmin`. A missing slot renders nothing, so
   * the package stays usable standalone.
   */
  memberFilterSlot?: React.ReactNode;
  projectFilterSlot?: React.ReactNode;
  dateRangeSlot?: React.ReactNode;
};

/** EStartOfTheWeek numbering (@plane/types) — SUNDAY = 0 .. SATURDAY = 6. */
const DAY_ABBR = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Formats `hours` without a trailing ".0" (e.g. "40h", "37.5h/week"). */
function formatWeeklyHours(hours: number): string {
  return Number.isInteger(hours) ? `${hours}` : hours.toFixed(1);
}

/** "Max 40h/week · Mon, Tue, Wed, Thu, Fri · week starts Monday" */
function formatWorkSettingsReadout(settings: TWorkSettings): string {
  const workdaysLabel = settings.workdays.map((d) => DAY_ABBR[d] ?? "?").join(", ");
  const weekStartLabel = DAY_ABBR[settings.week_start_day] ?? "?";
  return wlt("toolbar.settings_readout", {
    hours: formatWeeklyHours(settings.max_weekly_hours),
    workdays: workdaysLabel,
    weekStart: weekStartLabel,
  });
}

const STATE_GROUP_KEYS = Object.values(STATE_GROUPS);

// ── Component ─────────────────────────────────────────────────────────────────

export const WorkloadToolbar = observer(function WorkloadToolbar({
  store,
  workspaceSlug,
  isAdmin = false,
  workSettings,
  memberFilterSlot,
  projectFilterSlot,
  dateRangeSlot,
}: WorkloadToolbarProps) {
  /** State group is a server-side filter — toggling refetches. */
  function handleStateGroupToggle(key: string) {
    const next = store.selectedStateGroups.includes(key)
      ? store.selectedStateGroups.filter((g) => g !== key)
      : [...store.selectedStateGroups, key];
    store.setStateGroups(next);
    store.fetchWorkload(workspaceSlug);
  }

  const hasActiveFilters =
    store.selectedProjectIds.length > 0 || store.selectedAssigneeIds.length > 0 || store.selectedStateGroups.length > 0;

  function handleClearFilters() {
    store.setProjectIds([]);
    store.setAssigneeIds([]);
    store.setStateGroups([]);
    store.fetchWorkload(workspaceSlug);
  }

  const settingsHref = joinUrlPath(workspaceSlug, "settings/workload");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {/* Granularity is NOT a control here. It is derived from the timeline's
            own Week/Month/Quarter zoom (WorkloadTimelineRoot), so the page has
            exactly one time-range control instead of two that disagreed: this
            one set the server-side bucketing while the chart's set the pixel
            zoom, and nothing kept them in step. */}

        {/* Date range (app-injected) */}
        {dateRangeSlot}

        {/* Member + project filters (app-injected) */}
        {memberFilterSlot}
        {projectFilterSlot}

        {/* State groups */}
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label={wlt("filters.state_groups")}>
          {STATE_GROUP_KEYS.map((group) => {
            const isSelected = store.selectedStateGroups.includes(group.key);
            return (
              <button
                key={group.key}
                type="button"
                aria-pressed={isSelected}
                onClick={() => handleStateGroupToggle(group.key)}
                className={[
                  "text-13 flex items-center gap-1.5 rounded-md border px-2 py-1 transition-colors",
                  isSelected
                    ? "border-accent-subtle bg-accent-subtle text-accent-primary"
                    : "border-subtle text-tertiary hover:bg-layer-transparent-hover",
                ].join(" ")}
              >
                <span aria-hidden="true" className="size-2 rounded-full" style={{ backgroundColor: group.color }} />
                {group.label}
              </button>
            );
          })}
        </div>

        {hasActiveFilters && (
          <button
            type="button"
            onClick={handleClearFilters}
            className="ml-auto rounded-md px-2 py-1 text-13 text-tertiary transition-colors hover:text-primary"
          >
            {wlt("filters.clear")}
          </button>
        )}
      </div>

      {/* Workspace work-settings readout — read-only; undefined workSettings renders nothing
          (the host has not wired the app's useWorkSettings() hook to this slot yet). */}
      {workSettings && (
        <div className="flex items-center gap-2 text-13 text-tertiary">
          <span>{formatWorkSettingsReadout(workSettings)}</span>
          {isAdmin && (
            <a href={settingsHref} className="text-accent-primary hover:underline">
              {wlt("toolbar.manage_settings")}
            </a>
          )}
        </div>
      )}
    </div>
  );
});
