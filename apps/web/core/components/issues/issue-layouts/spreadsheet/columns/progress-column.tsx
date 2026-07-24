/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (SP2 workload) — documented core-edit exception.
 * Listed in docs/FORK.md "Frontend core-edit exceptions".
 *
 * Header <th> + body <td> for the fixed "Progress" column, appended after the
 * Estimated-hours column (which is itself appended after the
 * spreadsheetColumnsList loop). Not registered in SPREADSHEET_COLUMNS /
 * IIssueDisplayProperties, so it is always visible and needs no @plane/types
 * edit — same fixed-append mechanism the hours column proved.
 *
 * Progress source (see @plane/workload-ext progress.ts): parents use the
 * server-side hours-weighted rollup percent; leaves derive it from their
 * workflow state group, read from the states store here.
 */

import { observer } from "mobx-react";
import { ProgressBar, resolveProgress, wlt } from "@plane/workload-ext";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
import { useWorkloadEstimate } from "@/hooks/store/use-workload-estimate";

// ── Header cell ───────────────────────────────────────────────────────────────

export const ProgressHeaderCell = observer(function ProgressHeaderCell() {
  return (
    // The1Studio fork (SP2 workload) — fixed header column, not in SPREADSHEET_COLUMNS
    <th
      className="h-11 min-w-36 items-center border border-t-0 border-b-0 border-subtle bg-layer-1 py-1 text-13 font-medium"
      tabIndex={0}
    >
      <div className="flex h-full items-center px-page-x">
        <span className="truncate text-secondary">{wlt("progress.label")}</span>
      </div>
    </th>
  );
});

// ── Body cell ─────────────────────────────────────────────────────────────────

interface ProgressBodyCellProps {
  /** Issue id — reads the (parent) rollup from the shared workload store. */
  issueId: string;
  /** State id — leaf progress is derived from this state's group. */
  stateId: string | null | undefined;
}

export const ProgressBodyCell = observer(function ProgressBodyCell(props: ProgressBodyCellProps) {
  const { issueId, stateId } = props;

  const { rollup } = useWorkloadEstimate(issueId);
  const { getStateById } = useProjectState();
  const stateGroup = getStateById(stateId)?.group;

  const value = resolveProgress(rollup, stateGroup);

  return (
    // The1Studio fork (SP2 workload) — fixed body column, not in spreadsheetColumnsList
    <td
      tabIndex={0}
      className="h-11 min-w-36 border-r-[1px] border-subtle text-13 after:absolute after:bottom-[-1px] after:w-full after:border after:border-subtle"
    >
      <div className="flex h-full items-center border-b-[0.5px] border-subtle px-page-x">
        <ProgressBar value={value} ariaLabel={wlt("progress.label")} />
      </div>
    </td>
  );
});
