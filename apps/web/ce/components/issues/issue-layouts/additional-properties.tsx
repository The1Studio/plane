/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (SP2 workload) — estimated-hours pill for list/kanban rows.
 * Mounted via the WorkItemLayoutAdditionalProperties seam in all-properties.tsx.
 * This component is intentionally the ONLY place that renders the hours pill;
 * the seam is shared with kanban/block.tsx so the pill appears there too.
 */

import React from "react";
import { Timer } from "lucide-react";
import type { IIssueDisplayProperties, TIssue } from "@plane/types";
import { wlt } from "@plane/workload-ext";
import { useWorkloadEstimate } from "@/hooks/store/use-workload-estimate";

export type TWorkItemLayoutAdditionalProperties = {
  displayProperties: IIssueDisplayProperties;
  issue: TIssue;
};

export function WorkItemLayoutAdditionalProperties({ issue }: TWorkItemLayoutAdditionalProperties) {
  const { hours } = useWorkloadEstimate(issue.id);

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
