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
//   lane   — deliberately BLANK. Each bar already carries its own name and
//            hours and is the click target for the peek panel, so a sidebar
//            label only duplicated them — and for a lane packing several
//            non-overlapping tasks it could manage nothing better than
//            "N items", which names nothing. The cell survives purely as a
//            BLOCK_HEIGHT spacer (see the lane branch below for why).
//   footer — the Unscheduled / Overdue / truncation strip
//
// Splitting the footer out of the header is what lets this match the reference
// layout WITHOUT a core edit: a taller header row would need per-block heights
// that the shared primitive does not offer, whereas one more uniform-height
// block needs nothing from core at all.

import { ChevronDown, ChevronRight } from "lucide-react";
import { observer } from "mobx-react";
import { wlt } from "@plane/workload-ext";
import type { TWorkloadRow, TWorkloadTask } from "@plane/workload-ext";
import type { TFocusPeriod } from "./blocks";
import { Avatar, Row, ERowVariant } from "@plane/ui";
import { cn } from "@plane/utils";
import { useMember } from "@/hooks/store/use-member";
import { useTimeLineChartStore } from "@/hooks/use-timeline-chart";
import { BLOCK_HEIGHT } from "@/components/gantt-chart/constants";
import { UNASSIGNED_KEY, assigneeKey } from "./types";
import type { TWorkloadTimelineBlockData } from "./types";

type Props = {
  blockIds: string[];
  /**
   * A predicate rather than a set of collapsed keys: collapse has a per-zoom
   * DEFAULT that manual toggles override, so a key nobody has touched still has
   * an answer. See `WorkloadTimelineRoot` for the default + override model.
   */
  isCollapsed: (key: string) => boolean;
  onToggleCollapse: (key: string) => void;
  /**
   * The period the header badge reports on — derived once by the root from the
   * chart's centre and zoom (see `focusPeriodFor`), never re-derived per row.
   * `null` until the first viewport sync, when the badge reads "—" rather than
   * inventing a period.
   */
  focus: TFocusPeriod | null;
};

/** Two-decimal rounding, so summed float buckets do not print 7.000000000000001h. */
function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** "32h/40h" — omits the fractional ".0". */
function fmtHours(value: number): string {
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

/**
 * Is this bucket key inside the focused period?
 *
 * Keys are `YYYY-MM-DD` at day/week granularity and `YYYY-MM` at month. A bare
 * month key would compare as BEFORE its own month's first day under plain
 * string ordering (`"2026-08" < "2026-08-01"`), so it is widened to that first
 * day — attributing the bucket to the period containing its start, exactly as
 * the longer keys already do.
 */
function isInFocus(periodKey: string, focus: TFocusPeriod): boolean {
  const start = periodKey.length === 7 ? `${periodKey}-01` : periodKey;
  return start >= focus.from && start <= focus.to;
}

/**
 * The badge figures: hours booked and capacity available inside the focused
 * period, summed over the buckets that fall in it.
 *
 * Summing the VISIBLE buckets — rather than reading a dedicated per-week field
 * — is what lets one code path serve all three zooms, and it guarantees the
 * badge and the heat cells beside it can never disagree: they are literally the
 * same numbers. A period key is attributed to the period containing its start,
 * the same convention `period_key` uses server-side, so a week straddling two
 * months counts once, in the month it began.
 */
function periodFigures(
  row: TWorkloadRow,
  focus: TFocusPeriod | null
): { used: number; capacity: number; over: boolean; hasData: boolean } {
  let used = 0;
  let capacity = 0;
  let hasData = false;
  if (!focus) return { used, capacity, over: false, hasData };
  for (const [period, hours] of Object.entries(row.buckets ?? {})) {
    if (!isInFocus(period, focus)) continue;
    used += hours;
    hasData = true;
  }
  for (const [period, hours] of Object.entries(row.capacity_buckets ?? {})) {
    if (!isInFocus(period, focus)) continue;
    capacity += hours;
    hasData = true;
  }
  return {
    used: round2(used),
    capacity: round2(capacity),
    over: capacity > 0 && used > capacity,
    hasData,
  };
}

/** A fixed-height sidebar cell — every block kind occupies exactly one. */
function SidebarCell({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <Row variant={ERowVariant.HUGGING} className={className} style={{ height: `${BLOCK_HEIGHT}px` }}>
      {children}
    </Row>
  );
}

export const WorkloadTimelineSidebarRow = observer(function WorkloadTimelineSidebarRow({
  blockIds,
  isCollapsed,
  onToggleCollapse,
  focus,
}: Props) {
  const { getBlockById } = useTimeLineChartStore();
  const { getUserDetails } = useMember();

  return (
    <div>
      {blockIds.map((blockId) => {
        const block = getBlockById(blockId);
        const data = block?.data as TWorkloadTimelineBlockData | undefined;
        if (!data) return null;

        // ── lane ────────────────────────────────────────────────────────────
        if (data.kind === "lane") {
          // Intentionally empty — the bars are the label. Do NOT return `null`
          // or drop the branch: the chart body stacks one BlockRow per blockId
          // at a fixed BLOCK_HEIGHT, so a lane that renders no sidebar cell
          // shortens this column by 44px and slides every row BELOW it out of
          // alignment with its own bars, an error that accumulates down the
          // page. The cell is a spacer with nothing in it, which is not the
          // same thing as no cell.
          return <SidebarCell key={blockId} />;
        }

        // ── footer ──────────────────────────────────────────────────────────
        if (data.kind === "footer") {
          const { row } = data;
          const unscheduledCount = row.tasks.filter((t: TWorkloadTask) => !t.target_date).length;
          const overdueCount = row.tasks.filter((t: TWorkloadTask) => t.overdue).length;
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
        const rowCollapsed = isCollapsed(key);
        const memberDetails = data.assigneeId ? getUserDetails(data.assigneeId) : undefined;
        const { used, capacity, over, hasData } = periodFigures(row, focus);

        return (
          <SidebarCell key={blockId} className={cn("flex items-center gap-2 pr-2", { "bg-danger-subtle/40": over })}>
            <button
              type="button"
              onClick={() => onToggleCollapse(key)}
              className="flex-shrink-0 text-tertiary hover:text-primary"
              aria-label={rowCollapsed ? "Expand" : "Collapse"}
            >
              {rowCollapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
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
                title={focus?.label}
              >
                {hasData ? `${fmtHours(used)}h/${fmtHours(capacity)}h` : "—"}
              </span>
            </div>
          </SidebarCell>
        );
      })}
    </div>
  );
});
