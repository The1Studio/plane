// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline) — sidebar column for the workload
// timeline. Called ONCE by `GanttChartSidebar` (via `sidebarToRender`) with the
// full `blockIds` list, mirroring the existing `IssueGanttSidebar` pattern
// (`apps/web/core/components/gantt-chart/sidebar/issues/sidebar.tsx`): this
// component owns the per-blockId map internally rather than being called once
// per row.
//
// Three block kinds, all at core's shared BLOCK_HEIGHT (44px, hardcoded in
// `gantt-chart/blocks/block-row.tsx`):
//
//   header — avatar, name, weekly capacity badge, collapse chevron
//   task   — work-item identifier + name (the click target for the peek panel)
//   footer — the Unscheduled / Overdue / truncation strip
//
// Splitting the footer out of the header is what lets this match the reference
// layout WITHOUT a core edit: a taller header row would need per-block heights
// that the shared primitive does not offer, whereas one more uniform-height
// block needs nothing from core at all.

import { ChevronDown, ChevronRight } from "lucide-react";
import { observer } from "mobx-react";
import { wlt } from "@plane/workload-ext";
import type { TWorkloadRow } from "@plane/workload-ext";
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
  /**
   * The week the header badge reports on — a `weekly_buckets` key, computed
   * once by the root from the response window and the workspace's week start
   * (see `focusWeekKey`), not re-derived per row.
   */
  focusWeek: string;
  /** Renders a task row as a peek-opening control. Phase 4 supplies it. */
  renderTaskLabel?: (data: Extract<TWorkloadTimelineBlockData, { kind: "task" }>) => React.ReactNode;
};

/** "32h/40h" — omits the fractional ".0". */
function fmtHours(value: number): string {
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

/** Pretty-prints a `weekly_buckets` key ("2026-08-17") for the badge tooltip. */
function formatWeekLabel(weekKey: string): string {
  const d = new Date(`${weekKey}T00:00:00`);
  if (Number.isNaN(d.getTime())) return weekKey;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/**
 * The badge figures: hours logged in `focusWeek` against the workspace's
 * weekly max.
 *
 * This is deliberately NOT `row.total` over the summed `capacity_buckets`.
 * That window total answered a question nobody asked ("how loaded is this
 * person across the whole visible range?") in units the workspace never
 * configures — the setting is a WEEKLY maximum — and, before `periods` covered
 * the requested window, its denominator was capacity over whichever buckets
 * happened to contain hours, so it moved when an unrelated member scheduled
 * work. Per-period detail still lives on each heat cell's tooltip.
 */
function weeklyFigures(row: TWorkloadRow, focusWeek: string): { used: number; capacity: number; over: boolean } {
  const used = row.weekly_buckets?.[focusWeek] ?? 0;
  const capacity = row.weekly_capacity ?? 0;
  return { used, capacity, over: capacity > 0 && used > capacity };
}

/** A fixed-height sidebar cell — every block kind occupies exactly one. */
function SidebarCell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <Row variant={ERowVariant.HUGGING} className={className} style={{ height: `${BLOCK_HEIGHT}px` }}>
      {children}
    </Row>
  );
}

export const WorkloadTimelineSidebarRow = observer(function WorkloadTimelineSidebarRow({
  blockIds,
  collapsed,
  onToggleCollapse,
  focusWeek,
  renderTaskLabel,
}: Props) {
  const { getBlockById } = useTimeLineChartStore();
  const { getUserDetails } = useMember();

  return (
    <div>
      {blockIds.map((blockId) => {
        const block = getBlockById(blockId);
        const data = block?.data as TWorkloadTimelineBlockData | undefined;
        if (!data) return null;

        // ── task ────────────────────────────────────────────────────────────
        if (data.kind === "task") {
          const { task } = data;
          return (
            <SidebarCell key={blockId} className="flex items-center gap-2 pr-2 pl-7">
              {renderTaskLabel ? (
                renderTaskLabel(data)
              ) : (
                <div className="flex min-w-0 flex-1 items-center gap-1.5 truncate">
                  <span className="flex-shrink-0 text-11 font-medium text-tertiary tabular-nums">
                    {task.identifier}
                  </span>
                  <span className="truncate text-13">{task.name}</span>
                </div>
              )}
              <span className="flex-shrink-0 text-11 text-tertiary tabular-nums">{fmtHours(task.hours)}h</span>
            </SidebarCell>
          );
        }

        // ── footer ──────────────────────────────────────────────────────────
        if (data.kind === "footer") {
          const { row } = data;
          const unscheduledCount = row.tasks.filter((t) => !t.target_date).length;
          const overdueCount = row.tasks.filter((t) => t.overdue).length;
          return (
            <SidebarCell key={blockId} className="flex items-center gap-3 pr-2 pl-7 text-11 text-tertiary">
              {unscheduledCount > 0 && <span>{wlt("timeline.unscheduled_count", { count: unscheduledCount })}</span>}
              {overdueCount > 0 && (
                <span className="text-danger-primary">{wlt("timeline.overdue_count", { count: overdueCount })}</span>
              )}
              {row.tasks_truncated && (
                <span
                  className="text-warning-primary"
                  title={wlt("timeline.showing_first_n", { count: row.tasks.length })}
                >
                  {wlt("timeline.showing_first_n", { count: row.tasks.length })}
                </span>
              )}
            </SidebarCell>
          );
        }

        // ── header ──────────────────────────────────────────────────────────
        const { row } = data;
        const key = assigneeKey(data.assigneeId);
        const isCollapsed = collapsed.has(key);
        const memberDetails = data.assigneeId ? getUserDetails(data.assigneeId) : undefined;
        const { used, capacity, over } = weeklyFigures(row, focusWeek);

        return (
          <SidebarCell key={blockId} className={cn("flex items-center gap-2 pr-2", { "bg-danger-subtle/40": over })}>
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

            <div className="flex min-w-0 flex-1 items-center gap-1.5 truncate">
              <span className="truncate text-13 font-medium">
                {key === UNASSIGNED_KEY ? wlt("timeline.unassigned") : row.assignee_name}
              </span>
              <span
                className={cn(
                  "flex-shrink-0 text-11 tabular-nums",
                  over ? "font-medium text-danger-primary" : "text-tertiary"
                )}
                // Without this the reader cannot tell WHICH week "41h/40h" is
                // about — the chart axis may be scrolled anywhere.
                title={wlt("timeline.week_of", { date: formatWeekLabel(focusWeek) })}
              >
                {fmtHours(used)}h/{fmtHours(capacity)}h
              </span>
            </div>
          </SidebarCell>
        );
      })}
    </div>
  );
});
