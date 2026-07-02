/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (SP2 workload) — estimated-hours pill for list/kanban rows.
 * Mounted via the WorkItemLayoutAdditionalProperties seam in all-properties.tsx.
 * This component is intentionally the ONLY place that renders the hours pill;
 * the seam is shared with kanban/block.tsx so the pill appears there too.
 *
 * NOTE (plan §P4 item 5 deviation): the plan calls for a layout-aware
 * abbreviated pill in kanban ("Σ10h", no percent) vs. the full pill in list
 * ("Σ 10h · 60%"). `all-properties.tsx` (IssueProperties) already receives an
 * `activeLayout` prop from its list/kanban callers but does not forward it
 * into this seam, and `all-properties.tsx` is outside this task's file
 * ownership (not a documented fork-fenced hunk) — see the completion report
 * for the flagged one-line follow-up. Until that lands, both layouts render
 * the same rollup pill; `truncate` keeps it from clipping mid-character in
 * narrow kanban cards.
 */

import React from "react";
import { Timer } from "lucide-react";
import type { IIssueDisplayProperties, TIssue } from "@plane/types";
import { formatRollupPill, formatRollupTooltip, wlt } from "@plane/workload-ext";
import { useWorkloadEstimate } from "@/hooks/store/use-workload-estimate";

export type TWorkItemLayoutAdditionalProperties = {
  displayProperties: IIssueDisplayProperties;
  issue: TIssue;
};

export function WorkItemLayoutAdditionalProperties({ issue }: TWorkItemLayoutAdditionalProperties) {
  const { hours, rollup } = useWorkloadEstimate(issue.id);

  if (rollup) {
    return (
      <div
        className="flex h-5 flex-shrink-0 items-center justify-center gap-2 truncate overflow-hidden rounded-sm border-[0.5px] border-strong px-2.5 py-1"
        title={formatRollupTooltip(rollup)}
      >
        <Timer className="h-3 w-3 flex-shrink-0" strokeWidth={2} />
        <div className="truncate text-caption-sm-regular">{formatRollupPill(rollup)}</div>
      </div>
    );
  }

  // Render nothing when no estimate is recorded for this issue.
  if (hours === null || hours === undefined) return null;

  return (
    <div
      className="flex h-5 flex-shrink-0 items-center justify-center gap-2 overflow-hidden rounded-sm border-[0.5px] border-strong px-2.5 py-1"
      title={wlt("estimate.tooltip", { hours })}
    >
      <Timer className="h-3 w-3 flex-shrink-0" strokeWidth={2} />
      <div className="text-caption-sm-regular">{hours}h</div>
    </div>
  );
}
