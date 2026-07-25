import React from "react";
import { observer } from "mobx-react";

import { wlt } from "./i18n";
import type { IWorkloadStore } from "./store";

// ── Types ─────────────────────────────────────────────────────────────────────

type WorkloadFiltersProps = {
  store: IWorkloadStore;
  workspaceSlug: string;
  availableProjects?: Array<{ id: string; name: string }>;
  availableAssignees?: Array<{ id: string; display_name: string }>;
};

// ── Component ─────────────────────────────────────────────────────────────────

export const WorkloadFilters = observer(function WorkloadFilters({
  store,
  workspaceSlug,
  availableProjects = [],
  availableAssignees = [],
}: WorkloadFiltersProps) {
  function handleProjectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const ids = Array.from(e.target.selectedOptions, (opt) => opt.value);
    store.setProjectIds(ids);
  }

  function handleAssigneeChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const ids = Array.from(e.target.selectedOptions, (opt) => opt.value);
    store.setAssigneeIds(ids);
  }

  function handleFromChange(e: React.ChangeEvent<HTMLInputElement>) {
    store.setDateRange(e.target.value, store.dateTo);
  }

  function handleToChange(e: React.ChangeEvent<HTMLInputElement>) {
    store.setDateRange(store.dateFrom, e.target.value);
  }

  function handleRefresh() {
    store.fetchWorkload(workspaceSlug);
  }

  return (
    <div className="border-gray-200 bg-gray-50 flex flex-wrap items-end gap-4 rounded-lg border px-4 py-3">
      {/* Date from */}
      <div className="flex flex-col gap-1">
        <label htmlFor="wl-filter-from" className="text-xs text-gray-500 font-medium">
          {wlt("common.from")}
        </label>
        <input
          id="wl-filter-from"
          type="date"
          value={store.dateFrom}
          onChange={handleFromChange}
          className="border-gray-200 text-sm focus:ring-custom-primary-100 rounded border bg-white px-2 py-1.5 focus:ring-1 focus:outline-none"
        />
      </div>

      {/* Date to */}
      <div className="flex flex-col gap-1">
        <label htmlFor="wl-filter-to" className="text-xs text-gray-500 font-medium">
          {wlt("common.to")}
        </label>
        <input
          id="wl-filter-to"
          type="date"
          value={store.dateTo}
          min={store.dateFrom}
          onChange={handleToChange}
          className="border-gray-200 text-sm focus:ring-custom-primary-100 rounded border bg-white px-2 py-1.5 focus:ring-1 focus:outline-none"
        />
      </div>

      {/* Project multi-select */}
      <div className="flex flex-col gap-1">
        <label htmlFor="wl-filter-projects" className="text-xs text-gray-500 font-medium">
          {wlt("filters.projects")}
        </label>
        <select
          id="wl-filter-projects"
          multiple
          size={Math.min(4, Math.max(1, availableProjects.length))}
          value={store.selectedProjectIds}
          onChange={handleProjectChange}
          className="border-gray-200 text-sm focus:ring-custom-primary-100 min-w-[160px] rounded border bg-white px-2 py-1 focus:ring-1 focus:outline-none"
        >
          {availableProjects.length === 0 ? (
            <option disabled value="">
              {wlt("filters.no_projects")}
            </option>
          ) : (
            availableProjects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))
          )}
        </select>
      </div>

      {/* Assignee multi-select */}
      <div className="flex flex-col gap-1">
        <label htmlFor="wl-filter-assignees" className="text-xs text-gray-500 font-medium">
          {wlt("filters.assignees")}
        </label>
        <select
          id="wl-filter-assignees"
          multiple
          size={Math.min(4, Math.max(1, availableAssignees.length))}
          value={store.selectedAssigneeIds}
          onChange={handleAssigneeChange}
          className="border-gray-200 text-sm focus:ring-custom-primary-100 min-w-[160px] rounded border bg-white px-2 py-1 focus:ring-1 focus:outline-none"
        >
          {availableAssignees.length === 0 ? (
            <option disabled value="">
              {wlt("filters.no_assignees")}
            </option>
          ) : (
            availableAssignees.map((assignee) => (
              <option key={assignee.id} value={assignee.id}>
                {assignee.display_name}
              </option>
            ))
          )}
        </select>
      </div>

      {/* Over capacity only */}
      <div className="flex flex-col gap-1">
        <span className="text-xs text-gray-500 font-medium">&nbsp;</span>
        <label htmlFor="wl-filter-over-only" className="text-sm text-gray-700 flex h-[34px] items-center gap-2">
          <input
            id="wl-filter-over-only"
            type="checkbox"
            checked={store.showOverCapacityOnly}
            onChange={(e) => store.setShowOverCapacityOnly(e.target.checked)}
            className="focus:ring-custom-primary-100 rounded focus:ring-1 focus:outline-none"
          />
          {wlt("filters.over_only")}
        </label>
      </div>

      {/* Refresh button */}
      <button
        type="button"
        onClick={handleRefresh}
        disabled={store.isLoading}
        className="bg-custom-primary-100 text-sm rounded px-4 py-1.5 font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {store.isLoading ? wlt("common.loading") : wlt("common.refresh")}
      </button>
    </div>
  );
});
