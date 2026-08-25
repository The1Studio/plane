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
import { MAX_UNSCHEDULED_LANES, packTasksIntoLanes, selectPlaceholderTasks, unscheduledAnchorDate } from "../merge";
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
    state_name: "In Progress",
    state_color: "#f59e0b",
    unestimated: false,
    overdue: false,
  };
}

/**
 * The old `selectUnscheduledTasks(tasks, max)` in terms of the new selector:
 * the estimated-undated group, with no anchor filtering. Every assertion below
 * pins cap-and-order semantics that survived the split unchanged, so they are
 * kept as-is rather than rewritten around the new shape.
 */
const sel = (tasks: TWorkloadTask[], maxLanes?: number) =>
  selectPlaceholderTasks(tasks, TODAY, null, maxLanes).unscheduled;

describe("selectPlaceholderTasks — cap and ordering", () => {
  it("takes the first N in server order and counts the rest", () => {
    const tasks = [1, 2, 3, 4, 5].map((n) => task(String(n), null, null));
    const { shown, hiddenCount } = sel(tasks, 3);
    expect(shown.map((t) => t.id)).toEqual(["1", "2", "3"]);
    expect(hiddenCount).toBe(2);
  });

  it("hides nothing when everything fits", () => {
    const { shown, hiddenCount } = sel([task("1", null, null)], 3);
    expect(shown).toHaveLength(1);
    expect(hiddenCount).toBe(0);
  });

  it("returns an empty selection for a row with no tasks", () => {
    expect(sel([], 3)).toEqual({ shown: [], hiddenCount: 0 });
  });

  it("never returns a task that has a target date", () => {
    const tasks = [task("dated", "2026-08-01", "2026-08-05"), task("free", null, null)];
    expect(sel(tasks, 3).shown.map((t) => t.id)).toEqual(["free"]);
  });

  it("treats a start-only task as unscheduled — the packer drops it too", () => {
    // The load-bearing property: this selector and `packTasksIntoLanes` are
    // complements. A task neither of them returns is work that has silently
    // disappeared from the board.
    const startOnly = task("start-only", "2026-08-20", null);
    expect(sel([startOnly], 3).shown).toHaveLength(1);
    expect(packTasksIntoLanes([startOnly])).toEqual([]);
  });

  it("partitions every task between the two, with no task in both", () => {
    const tasks = [
      task("a", "2026-08-01", "2026-08-02"),
      task("b", null, null),
      task("c", "2026-08-10", null),
      task("d", null, "2026-08-15"),
    ];
    const unscheduledIds = sel(tasks, 99).shown.map((t) => t.id);
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
    sel(tasks, 1);
    expect(tasks.map((t) => t.id)).toEqual(before);
  });

  it("defaults to MAX_UNSCHEDULED_LANES", () => {
    const tasks = Array.from({ length: 10 }, (_, i) => task(String(i), null, null));
    expect(sel(tasks).shown).toHaveLength(MAX_UNSCHEDULED_LANES);
  });

  it("draws nothing and counts everything when the cap is zero or negative", () => {
    const tasks = [task("1", null, null), task("2", null, null)];
    expect(sel(tasks, 0)).toEqual({ shown: [], hiddenCount: 2 });
    expect(sel(tasks, -1)).toEqual({ shown: [], hiddenCount: 2 });
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

describe("selectPlaceholderTasks — the two budgets", () => {
  const unest = (id: string, start: string | null = null): TWorkloadTask => ({
    ...task(id, start, null),
    unestimated: true,
  });

  it("gives each group its own budget rather than sharing one", () => {
    // The regression: `_task_sort_key` sorts unestimated first, so under a
    // single shared cap of 3 these two unestimated rows took the top slots and
    // left exactly one of the four unscheduled ones visible.
    const tasks = [unest("u1"), unest("u2"), ...[1, 2, 3, 4].map((n) => task(`s${n}`, null, null))];

    const { unscheduled, unestimated } = selectPlaceholderTasks(tasks, TODAY, null, 3);
    expect(unscheduled.shown.map((t) => t.id)).toEqual(["s1", "s2", "s3"]);
    expect(unscheduled.hiddenCount).toBe(1);
    expect(unestimated.shown.map((t) => t.id)).toEqual(["u1", "u2"]);
    expect(unestimated.hiddenCount).toBe(0);
  });

  it("puts an undated task in exactly one group, never both", () => {
    const tasks = [unest("u"), task("s", null, null)];
    const { unscheduled, unestimated } = selectPlaceholderTasks(tasks, TODAY, null, 3);

    const drawn = [...unscheduled.shown, ...unestimated.shown].map((t) => t.id);
    expect(drawn.toSorted()).toEqual(["s", "u"]);
  });

  it("pushes an out-of-window anchor into the overflow instead of drawing it off-screen", () => {
    // A start-only task is anchored at its own start, so one dated months back
    // paints outside the visible columns: it burned a slot AND, by counting as
    // shown, was missing from the overflow number too.
    const far = task("far", "2026-06-22", null);
    const here = [1, 2, 3].map((n) => task(`n${n}`, null, null));
    const win = { from: "2026-08-17", to: "2026-08-30" };

    const { unscheduled } = selectPlaceholderTasks([far, ...here], TODAY, win, 3);
    expect(unscheduled.shown.map((t) => t.id)).toEqual(["n1", "n2", "n3"]);
    expect(unscheduled.hiddenCount).toBe(1);
  });

  it("keeps a start-only task whose own anchor IS inside the window", () => {
    // The complement of the test above: the filter is on the ANCHOR, not on
    // having a start date, so a start-only task still draws where it belongs.
    const inside = task("inside", "2026-08-20", null);
    const win = { from: "2026-08-17", to: "2026-08-30" };

    const { unscheduled } = selectPlaceholderTasks([inside], TODAY, win, 3);
    expect(unscheduled.shown.map((t) => t.id)).toEqual(["inside"]);
    expect(unscheduled.hiddenCount).toBe(0);
  });

  it("counts hidden against the WHOLE group, not the drawable subset", () => {
    // Otherwise the footer answers "how many did the cap drop" instead of
    // "how many am I not looking at", and silently loses the filtered ones.
    const win = { from: "2026-08-17", to: "2026-08-30" };
    const tasks = [task("far1", "2026-01-01", null), task("far2", "2026-01-02", null), task("near", null, null)];

    const { unscheduled } = selectPlaceholderTasks(tasks, TODAY, win, 3);
    expect(unscheduled.shown.map((t) => t.id)).toEqual(["near"]);
    expect(unscheduled.hiddenCount).toBe(2);
  });

  it("draws nothing when today itself has been scrolled out of the window", () => {
    // Undated tasks anchor at today, so scrolling away from it legitimately
    // empties the placeholder lanes — the footer still reports them.
    const tasks = [task("a", null, null), task("b", null, null)];
    const win = { from: "2026-10-05", to: "2026-10-18" };

    const { unscheduled } = selectPlaceholderTasks(tasks, TODAY, win, 3);
    expect(unscheduled.shown).toEqual([]);
    expect(unscheduled.hiddenCount).toBe(2);
  });
});
