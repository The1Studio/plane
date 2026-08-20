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

import { observer } from "mobx-react";
// workload i18n (fork-owned strings — no @plane/i18n edit)
import { formatRollupHours, formatRollupTooltip, wlt } from "@plane/workload-ext";
// hooks
import { useWorkloadEstimate } from "@/hooks/store/use-workload-estimate";
import { useWorkloadEstimateEditor } from "@/hooks/store/use-workload-estimate-editor";

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

  // Rollup presence is the parent signal — a parent renders read-only.
  const { rollup } = useWorkloadEstimate(issueId);

  // Shared commit lifecycle: 800 ms after typing stops, on Enter (focus kept),
  // or on blur. See hooks/store/use-workload-estimate-editor.ts.
  const estimate = useWorkloadEstimateEditor({ workspaceSlug, projectId, issueId });

  return (
    // The1Studio fork (SP2 workload) — fixed body column, not in spreadsheetColumnsList
    <td
      tabIndex={0}
      className="h-11 min-w-36 border-r-[1px] border-subtle text-13 after:absolute after:bottom-[-1px] after:w-full after:border after:border-subtle"
    >
      <div className="flex h-full items-center gap-1 border-b-[0.5px] border-subtle px-page-x">
        {rollup ? (
          // Parent issue — read-only rollup summary, same disable intent as
          // the sidebar field (plan §P4 item 5).
          <span className="w-full truncate text-13 text-secondary" title={formatRollupTooltip(rollup)}>
            {formatRollupHours(rollup)}
          </span>
        ) : (
          <input
            type="number"
            min={0}
            max={10000}
            step={0.5}
            value={estimate.value}
            onFocus={estimate.onFocus}
            onChange={estimate.onChange}
            onBlur={estimate.onBlur}
            onKeyDown={estimate.onKeyDown}
            // NOTE: `estimate.isSaving` must NOT appear here. Saves now fire while
            // the user is still typing, so disabling on save drops focus mid-edit.
            disabled={disableUserActions || !projectId}
            placeholder={wlt("common.none")}
            className="w-full bg-transparent text-13 text-primary outline-none placeholder:text-placeholder disabled:cursor-not-allowed disabled:opacity-60"
          />
        )}
        {estimate.isSaving && <span className="text-xs shrink-0 text-secondary">{wlt("common.saving")}</span>}
      </div>
    </td>
  );
});
