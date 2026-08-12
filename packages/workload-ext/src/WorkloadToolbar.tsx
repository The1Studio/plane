import React from "react";
import { observer } from "mobx-react";
import { STATE_GROUPS } from "@plane/constants";
import { Switch } from "@plane/propel/switch";
import { Tabs } from "@plane/propel/tabs";

import { wlt } from "./i18n";
import type { IWorkloadStore } from "./store";
import type { TWorkloadGranularity } from "./types";

// ── Types ─────────────────────────────────────────────────────────────────────

export type WorkloadToolbarProps = {
  store: IWorkloadStore;
  workspaceSlug: string;
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

const GRANULARITIES: Array<{ value: TWorkloadGranularity; labelKey: Parameters<typeof wlt>[0] }> = [
  { value: "day", labelKey: "granularity.day" },
  { value: "week", labelKey: "granularity.week" },
  { value: "month", labelKey: "granularity.month" },
];

const STATE_GROUP_KEYS = Object.values(STATE_GROUPS);

// ── Component ─────────────────────────────────────────────────────────────────

export const WorkloadToolbar = observer(function WorkloadToolbar({
  store,
  workspaceSlug,
  memberFilterSlot,
  projectFilterSlot,
  dateRangeSlot,
}: WorkloadToolbarProps) {
  function handleGranularityChange(value: unknown) {
    // base-ui can emit a null value on deselect — ignore it rather than
    // sending `granularity=null` to the API (mirrors the propel Tabs stories).
    if (typeof value !== "string") return;
    store.setGranularity(value as TWorkloadGranularity);
    store.fetchWorkload(workspaceSlug);
  }

  /** State group is a server-side filter — toggling refetches. */
  function handleStateGroupToggle(key: string) {
    const next = store.selectedStateGroups.includes(key)
      ? store.selectedStateGroups.filter((g) => g !== key)
      : [...store.selectedStateGroups, key];
    store.setStateGroups(next);
    store.fetchWorkload(workspaceSlug);
  }

  /** Over-capacity is a client-side row filter (plan D-B4) — never refetches. */
  function handleOverOnlyChange(value: boolean) {
    store.setShowOverCapacityOnly(value);
  }

  const hasActiveFilters =
    store.selectedProjectIds.length > 0 ||
    store.selectedAssigneeIds.length > 0 ||
    store.selectedStateGroups.length > 0 ||
    store.showOverCapacityOnly;

  function handleClearFilters() {
    store.setProjectIds([]);
    store.setAssigneeIds([]);
    store.setStateGroups([]);
    store.setShowOverCapacityOnly(false);
    store.fetchWorkload(workspaceSlug);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Granularity */}
      <Tabs
        value={store.granularity}
        onValueChange={handleGranularityChange}
        className="h-auto w-auto"
        aria-label={wlt("filters.granularity")}
      >
        <Tabs.List className="w-auto">
          {GRANULARITIES.map(({ value, labelKey }) => (
            <Tabs.Trigger key={value} value={value} className="px-3">
              {wlt(labelKey)}
            </Tabs.Trigger>
          ))}
          <Tabs.Indicator />
        </Tabs.List>
      </Tabs>

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

      {/* Over-capacity only — client-side, no refetch */}
      <div className="ml-1 flex items-center gap-2">
        <Switch value={store.showOverCapacityOnly} onChange={handleOverOnlyChange} label={wlt("filters.over_only")} />
        {/* Switch renders `label` as aria-label only, so the visible text lives here. */}
        <button
          type="button"
          onClick={() => handleOverOnlyChange(!store.showOverCapacityOnly)}
          className="text-13 text-tertiary transition-colors hover:text-primary"
        >
          {wlt("filters.over_only")}
        </button>
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
  );
});
