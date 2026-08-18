// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline, phase-8.md) — sidebar column for the
// workload timeline. Called ONCE by `GanttChartSidebar` (via `sidebarToRender`)
// with the full `blockIds` list, mirroring the existing `IssueGanttSidebar`
// pattern (`apps/web/core/components/gantt-chart/sidebar/issues/sidebar.tsx`):
// this component owns the per-blockId map internally rather than being called
// once per row.
//
// `task`-kind blocks render an empty spacer here — the mock (phase-8.md) has
// no per-task sidebar content; every task's detail lives on its bar in the
// chart body. BLOCK_HEIGHT is a shared constant (44px) applied uniformly to
// EVERY row by the reused `BlockRow`/`GanttChartBlock` components, so the
// header row's avatar/badge/chevron/affordances are laid out on one line
// rather than the two-line sketch in the mock — growing the row would need
// per-block height support the primitive doesn't have (see the Root
// component's docstring for the fuller composition rationale).

import { ChevronDown, ChevronRight } from "lucide-react";
import { observer } from "mobx-react";
import { wlt } from "@plane/workload-ext";
import { Avatar, Row, ERowVariant } from "@plane/ui";
import { cn } from "@plane/utils";
import { useMember } from "@/hooks/store/use-member";
import { useTimeLineChartStore } from "@/hooks/use-timeline-chart";
import { BLOCK_HEIGHT } from "@/components/gantt-chart/constants";
import { UNASSIGNED_KEY, assigneeKey } from "./types";
import type { TWorkloadTimelineBlockData } from "./types";

type Props = {
  blockIds: string[];
  collapsed: ReadonlySet<string>;
  onToggleCollapse: (key: string) => void;
};

/** "32h/40h" — omits the fractional ".0". */
function fmtHours(value: number): string {
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

export const WorkloadTimelineSidebarRow = observer(function WorkloadTimelineSidebarRow({
  blockIds,
  collapsed,
  onToggleCollapse,
}: Props) {
  const { getBlockById } = useTimeLineChartStore();
  const { getUserDetails } = useMember();

  return (
    <div>
      {blockIds.map((blockId) => {
        const block = getBlockById(blockId);
        const data = block?.data as TWorkloadTimelineBlockData | undefined;
        if (!data) return null;

        if (data.kind === "task") {
          // Spacer — keeps this sidebar row vertically aligned with its task
          // bar's row in the chart body (BlockRow stacks purely by blockIds
          // order/count, so every entry needs a same-height sidebar cell).
          return (
            <Row key={blockId} style={{ height: `${BLOCK_HEIGHT}px` }} variant={ERowVariant.HUGGING}>
              {null}
            </Row>
          );
        }

        const { row } = data;
        const key = assigneeKey(data.assigneeId);
        const isCollapsed = collapsed.has(key);
        const memberDetails = data.assigneeId ? getUserDetails(data.assigneeId) : undefined;
        const capacityTotal = Object.values(row.capacity_buckets ?? {}).reduce((sum, v) => sum + v, 0);
        const unscheduledCount = row.tasks.filter((t) => !t.target_date).length;
        const overdueCount = row.tasks.filter((t) => t.overdue).length;

        return (
          <Row
            key={blockId}
            variant={ERowVariant.HUGGING}
            className={cn("flex items-center gap-2 pr-2", { "bg-danger-subtle/40": row.total_over })}
            style={{ height: `${BLOCK_HEIGHT}px` }}
          >
            <button
              type="button"
              onClick={() => onToggleCollapse(key)}
              className="flex-shrink-0 text-tertiary hover:text-primary"
              aria-label={isCollapsed ? "Expand" : "Collapse"}
            >
              {isCollapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
            </button>

            {key === UNASSIGNED_KEY ? (
              <Avatar name={wlt("timeline.unassigned")} size="sm" showTooltip={false} />
            ) : (
              <Avatar name={row.assignee_name} src={memberDetails?.avatar_url} size="sm" showTooltip={false} />
            )}

            <div className="flex min-w-0 flex-1 flex-col justify-center truncate">
              <div className="flex items-center gap-1.5 truncate">
                <span className="truncate text-13 font-medium">
                  {key === UNASSIGNED_KEY ? wlt("timeline.unassigned") : row.assignee_name}
                </span>
                <span
                  className={cn(
                    "flex-shrink-0 text-11 tabular-nums",
                    row.total_over ? "font-medium text-danger-primary" : "text-tertiary"
                  )}
                >
                  {fmtHours(row.total)}h/{fmtHours(capacityTotal)}h
                </span>
              </div>
              {(unscheduledCount > 0 || overdueCount > 0 || row.tasks_truncated) && (
                <div className="flex items-center gap-1.5 truncate text-11 text-tertiary">
                  {unscheduledCount > 0 && (
                    <span>{wlt("timeline.unscheduled_count", { count: unscheduledCount })}</span>
                  )}
                  {overdueCount > 0 && (
                    <span className="text-danger-primary">
                      {wlt("timeline.overdue_count", { count: overdueCount })}
                    </span>
                  )}
                  {row.tasks_truncated && (
                    <span
                      className="text-warning-primary"
                      title={wlt("timeline.showing_first_n", { count: row.tasks.length })}
                    >
                      {wlt("timeline.showing_first_n", { count: row.tasks.length })}
                    </span>
                  )}
                </div>
              )}
            </div>
          </Row>
        );
      })}
    </div>
  );
});
