// Tests for the estimated/unestimated split that feeds the timeline's two
// lane groups.
//
// The properties worth pinning are the ones a screenshot would not reveal:
// that the split is keyed on the FLAG and not on `hours === 0` (a stored
// zero-hour estimate is a real, reachable state), that it partitions rather
// than samples — nothing gained, nothing lost — that it preserves the server's
// deliberate ordering, and that it composes with the unscheduled selector
// instead of competing with it.

import { describe, expect, it } from "vitest";
import { packTasksIntoLanes, selectUnscheduledTasks, splitByEstimate } from "../merge";
import type { TWorkloadTask } from "../types";

function task(
  id: string,
  {
    start = null,
    target = null,
    unestimated = false,
    hours = 4,
  }: { start?: string | null; target?: string | null; unestimated?: boolean; hours?: number } = {}
): TWorkloadTask {
  return {
    id,
    project_id: "p1",
    identifier: `TEST-${id}`,
    name: `task ${id}`,
    hours,
    total_hours: hours,
    assignee_count: 1,
    start_date: start,
    target_date: target,
    state_group: "started",
    state_name: "In Progress",
    state_color: "#f59e0b",
    unestimated,
    overdue: false,
  };
}

describe("splitByEstimate", () => {
  it("partitions: every task lands in exactly one side", () => {
    const tasks = [
      task("1", { unestimated: false }),
      task("2", { unestimated: true }),
      task("3", { unestimated: false }),
      task("4", { unestimated: true }),
    ];
    const { estimated, unestimated } = splitByEstimate(tasks);

    expect(estimated.map((t) => t.id)).toEqual(["1", "3"]);
    expect(unestimated.map((t) => t.id)).toEqual(["2", "4"]);
    // Nothing gained, nothing lost — a filter typo that dropped or duplicated
    // a row would pass the two assertions above but fail this one.
    expect([...estimated, ...unestimated]).toHaveLength(tasks.length);
    expect(new Set([...estimated, ...unestimated].map((t) => t.id))).toEqual(new Set(tasks.map((t) => t.id)));
  });

  it("keys on the flag, never on hours === 0", () => {
    // A stored zero-hour estimate is the exact case the arithmetic test gets
    // wrong, and it is reachable in production — the API reports it in
    // `meta.zero_estimate_count`.
    const zeroButEstimated = task("z", { hours: 0, unestimated: false });
    const unestimatedWithHours = task("u", { hours: 0, unestimated: true });
    const { estimated, unestimated } = splitByEstimate([zeroButEstimated, unestimatedWithHours]);

    expect(estimated.map((t) => t.id)).toEqual(["z"]);
    expect(unestimated.map((t) => t.id)).toEqual(["u"]);
  });

  it("preserves server order within each side", () => {
    // `_task_sort_key` already ordered these; re-sorting here would make bars
    // swap places between refetches for no reason the reader could see.
    const tasks = [
      task("b", { unestimated: true, target: "2026-09-02" }),
      task("a", { unestimated: true, target: "2026-09-01" }),
      task("d", { target: "2026-09-04" }),
      task("c", { target: "2026-09-03" }),
    ];
    const { estimated, unestimated } = splitByEstimate(tasks);

    expect(unestimated.map((t) => t.id)).toEqual(["b", "a"]);
    expect(estimated.map((t) => t.id)).toEqual(["d", "c"]);
  });

  it("does not mutate the input array or its tasks", () => {
    const tasks = [task("1", { unestimated: true }), task("2")];
    const snapshot = JSON.stringify(tasks);
    const { estimated, unestimated } = splitByEstimate(tasks);

    expect(JSON.stringify(tasks)).toBe(snapshot);
    expect(estimated).not.toBe(tasks);
    expect(unestimated).not.toBe(tasks);
  });

  it("handles the all-one-kind and empty cases", () => {
    expect(splitByEstimate([])).toEqual({ estimated: [], unestimated: [] });

    const allUnestimated = [task("1", { unestimated: true }), task("2", { unestimated: true })];
    expect(splitByEstimate(allUnestimated).estimated).toEqual([]);
    expect(splitByEstimate(allUnestimated).unestimated).toHaveLength(2);
  });
});

describe("splitByEstimate composes with the scheduled/unscheduled split", () => {
  it("an undated unestimated task is still selected as a placeholder", () => {
    // The two splits are ORTHOGONAL. If `selectUnscheduledTasks` stopped
    // seeing unestimated rows, an undated unestimated item would be drawn by
    // nobody: `packTasksIntoLanes` drops it for having no target.
    const undatedUnestimated = task("u", { unestimated: true });
    const { shown } = selectUnscheduledTasks([undatedUnestimated]);

    expect(shown.map((t) => t.id)).toEqual(["u"]);
  });

  it("a dated unestimated task is lane-packed, not placed in the placeholder lanes", () => {
    const dated = task("d", { start: "2026-09-01", target: "2026-09-03", unestimated: true });
    const { unestimated } = splitByEstimate([dated]);

    expect(selectUnscheduledTasks([dated]).shown).toEqual([]);
    expect(packTasksIntoLanes(unestimated)).toEqual([[dated]]);
  });

  it("every task is drawn exactly once across the three groups", () => {
    // The board's completeness invariant, asserted directly: placeholder
    // lanes + unestimated lanes + estimated lanes must cover the row's tasks
    // with no overlap and no gap.
    const tasks = [
      task("est-dated", { start: "2026-09-01", target: "2026-09-02" }),
      task("est-undated"),
      task("unest-dated", { start: "2026-09-01", target: "2026-09-02", unestimated: true }),
      task("unest-undated", { unestimated: true }),
    ];

    const placeholders = selectUnscheduledTasks(tasks, 10).shown;
    const { estimated, unestimated } = splitByEstimate(tasks);
    const drawn = [...placeholders, ...packTasksIntoLanes(unestimated).flat(), ...packTasksIntoLanes(estimated).flat()];

    expect(drawn).toHaveLength(tasks.length);
    expect(new Set(drawn.map((t) => t.id))).toEqual(new Set(tasks.map((t) => t.id)));
  });
});
