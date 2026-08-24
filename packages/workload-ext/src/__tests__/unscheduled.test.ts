// Tests for the unscheduled-task selector and its anchor rule
// (plans/260824-workload-unscheduled-in-today/phase-3-selector-and-blocks.md).
//
// These two functions decide what a reader SEES of the work that carries no
// target date — until now it survived only as a number in the swimlane footer.
// The properties worth pinning are the ones a screenshot would not reveal:
// that the selector and `packTasksIntoLanes` stay exact complements (anything
// one drops, the other must show, or the work vanishes from the board), that
// the response object is never mutated, and that a task carrying a start of
// its own is anchored there rather than dragged to today.

import { describe, expect, it } from "vitest";
import { MAX_UNSCHEDULED_LANES, packTasksIntoLanes, selectUnscheduledTasks, unscheduledAnchorDate } from "../merge";
import type { TWorkloadTask } from "../types";

const TODAY = "2026-08-24";

function task(id: string, start: string | null, target: string | null): TWorkloadTask {
  return {
    id,
    project_id: "p1",
    identifier: `TEST-${id}`,
    name: `task ${id}`,
    hours: 4,
    total_hours: 4,
    assignee_count: 1,
    start_date: start,
    target_date: target,
    state_group: "started",
    overdue: false,
  };
}

describe("selectUnscheduledTasks", () => {
  it("takes the first N in server order and counts the rest", () => {
    const tasks = [1, 2, 3, 4, 5].map((n) => task(String(n), null, null));
    const { shown, hiddenCount } = selectUnscheduledTasks(tasks, 3);
    expect(shown.map((t) => t.id)).toEqual(["1", "2", "3"]);
    expect(hiddenCount).toBe(2);
  });

  it("hides nothing when everything fits", () => {
    const { shown, hiddenCount } = selectUnscheduledTasks([task("1", null, null)], 3);
    expect(shown).toHaveLength(1);
    expect(hiddenCount).toBe(0);
  });

  it("returns an empty selection for a row with no tasks", () => {
    expect(selectUnscheduledTasks([], 3)).toEqual({ shown: [], hiddenCount: 0 });
  });

  it("never returns a task that has a target date", () => {
    const tasks = [task("dated", "2026-08-01", "2026-08-05"), task("free", null, null)];
    expect(selectUnscheduledTasks(tasks, 3).shown.map((t) => t.id)).toEqual(["free"]);
  });

  it("treats a start-only task as unscheduled — the packer drops it too", () => {
    // The load-bearing property: this selector and `packTasksIntoLanes` are
    // complements. A task neither of them returns is work that has silently
    // disappeared from the board.
    const startOnly = task("start-only", "2026-08-20", null);
    expect(selectUnscheduledTasks([startOnly], 3).shown).toHaveLength(1);
    expect(packTasksIntoLanes([startOnly])).toEqual([]);
  });

  it("partitions every task between the two, with no task in both", () => {
    const tasks = [
      task("a", "2026-08-01", "2026-08-02"),
      task("b", null, null),
      task("c", "2026-08-10", null),
      task("d", null, "2026-08-15"),
    ];
    const unscheduledIds = selectUnscheduledTasks(tasks, 99).shown.map((t) => t.id);
    const lanedIds = packTasksIntoLanes(tasks)
      .flat()
      .map((t) => t.id);
    expect([...unscheduledIds, ...lanedIds].toSorted()).toEqual(["a", "b", "c", "d"]);
    expect(unscheduledIds.filter((id) => lanedIds.includes(id))).toEqual([]);
  });

  it("does not mutate the array it is given", () => {
    // That array belongs to the store's response object; reordering it during
    // a render would mutate observable state.
    const tasks = [task("1", null, null), task("2", null, null)];
    const before = tasks.map((t) => t.id);
    selectUnscheduledTasks(tasks, 1);
    expect(tasks.map((t) => t.id)).toEqual(before);
  });

  it("defaults to MAX_UNSCHEDULED_LANES", () => {
    const tasks = Array.from({ length: 10 }, (_, i) => task(String(i), null, null));
    expect(selectUnscheduledTasks(tasks).shown).toHaveLength(MAX_UNSCHEDULED_LANES);
  });

  it("draws nothing and counts everything when the cap is zero or negative", () => {
    const tasks = [task("1", null, null), task("2", null, null)];
    expect(selectUnscheduledTasks(tasks, 0)).toEqual({ shown: [], hiddenCount: 2 });
    expect(selectUnscheduledTasks(tasks, -1)).toEqual({ shown: [], hiddenCount: 2 });
  });
});

describe("unscheduledAnchorDate", () => {
  it("anchors a fully dateless task at today", () => {
    expect(unscheduledAnchorDate(task("1", null, null), TODAY)).toBe(TODAY);
  });

  it("anchors a start-only task at its OWN start, not today", () => {
    // Somebody chose that date. Drawing the bar at today would overwrite their
    // choice visually — and once the bar is draggable, its position is a claim
    // about a date rather than decoration.
    expect(unscheduledAnchorDate(task("1", "2026-08-20", null), TODAY)).toBe("2026-08-20");
  });
});
