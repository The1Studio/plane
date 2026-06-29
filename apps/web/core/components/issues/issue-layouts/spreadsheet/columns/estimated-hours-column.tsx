/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (SP2 workload) — documented core-edit exception.
 * Listed in docs/FORK.md "Frontend core-edit exceptions".
 *
 * Provides the header <th> and body <td> for the fixed "Estimated hours"
 * column appended after the spreadsheetColumnsList loop.  Not registered in
 * SPREADSHEET_COLUMNS / IIssueDisplayProperties, so it is always visible and
 * requires no @plane/types edit.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// workload i18n (fork-owned strings — no @plane/i18n edit)
import { wlt } from "@plane/workload-ext";
// hooks
import { useWorkload } from "@/hooks/store/use-workload";
import { useWorkloadEstimate } from "@/hooks/store/use-workload-estimate";

// ── Header cell ───────────────────────────────────────────────────────────────

/**
 * Fixed <th> appended after the spreadsheetColumnsList loop in
 * spreadsheet-header.tsx.  Matches the styling of SpreadsheetHeaderColumn's
 * inner <th>.
 */
export const EstimatedHoursHeaderCell = observer(function EstimatedHoursHeaderCell() {
  return (
    // The1Studio fork (SP2 workload) — fixed header column, not in SPREADSHEET_COLUMNS
    <th
      className="h-11 min-w-36 items-center border border-t-0 border-b-0 border-subtle bg-layer-1 py-1 text-13 font-medium"
      tabIndex={0}
    >
      <div className="flex h-full items-center px-page-x">
        <span className="truncate text-secondary">{wlt("estimate.label")}</span>
      </div>
    </th>
  );
});

// ── Body cell ─────────────────────────────────────────────────────────────────

interface EstimatedHoursBodyCellProps {
  /** Issue id for reading and writing the estimate. */
  issueId: string;
  /** Project id sourced from issueDetail.project_id (per-row, never route params). */
  projectId: string | null | undefined;
  /** Workspace slug used for the store mutation. */
  workspaceSlug: string;
  /**
   * When true the input is disabled.  This must be the real signal computed
   * as !canEditProperties(issueDetail.project_id) — NOT a non-existent
   * isEditable prop.
   */
  disableUserActions: boolean;
}

/**
 * Fixed <td> appended after the spreadsheetColumnsList loop in
 * IssueRowDetails (issue-row.tsx).  Mirrors the editable-input pattern from
 * issue-detail/sidebar.tsx ~lines 258-275.
 */
export const EstimatedHoursBodyCell = observer(function EstimatedHoursBodyCell(props: EstimatedHoursBodyCellProps) {
  const { issueId, projectId, workspaceSlug, disableUserActions } = props;

  // Read current value from shared store via selector hook.
  const { hours } = useWorkloadEstimate(issueId);

  // Local controlled value keeps the input responsive during typing.
  const [localValue, setLocalValue] = useState<string>("");
  const [isFocused, setIsFocused] = useState(false);
  const [saving, setSaving] = useState(false);

  const store = useWorkload();

  // While the field is focused we use the local draft value; otherwise we
  // display the persisted store value so it updates when the bulk fetch lands.
  const displayValue = isFocused ? localValue : hours !== null ? String(hours) : "";

  const handleFocus = () => {
    // Seed the local draft from the current stored value.
    setLocalValue(hours !== null ? String(hours) : "");
    setIsFocused(true);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setLocalValue(e.target.value);
  };

  const handleBlur = async () => {
    setIsFocused(false);

    if (!workspaceSlug || !projectId) return;

    // An empty field is treated as 0 (MEMBER-allowed PUT).
    // The ADMIN-only delete path is intentionally avoided.
    const parsed = localValue === "" ? 0 : Number(localValue);

    // Skip the round-trip when the value hasn't changed.
    const currentHours = hours ?? 0;
    if (parsed === currentHours) return;

    setSaving(true);
    try {
      await store.updateEstimate(workspaceSlug, projectId, issueId, parsed);
    } finally {
      setSaving(false);
    }
  };

  return (
    // The1Studio fork (SP2 workload) — fixed body column, not in spreadsheetColumnsList
    <td
      tabIndex={0}
      className="h-11 min-w-36 border-r-[1px] border-subtle text-13 after:absolute after:bottom-[-1px] after:w-full after:border after:border-subtle"
    >
      <div className="flex h-full items-center gap-1 border-b-[0.5px] border-subtle px-page-x">
        <input
          type="number"
          min={0}
          max={10000}
          step={0.5}
          value={displayValue}
          onFocus={handleFocus}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={disableUserActions || saving || !projectId}
          placeholder={wlt("common.none")}
          className="w-full bg-transparent text-13 text-primary outline-none placeholder:text-placeholder disabled:cursor-not-allowed disabled:opacity-60"
        />
        {saving && <span className="text-xs shrink-0 text-secondary">{wlt("common.saving")}</span>}
      </div>
    </td>
  );
});
