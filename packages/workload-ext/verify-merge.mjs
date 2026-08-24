// Hand-runnable checks for the range algebra + response merging in `src/merge.ts`.
//
// NOT WIRED INTO CI. This monorepo has no root `test` script and no JS test job,
// so a vitest suite added here would never execute — which is worse than an
// honest manual script, because it would look like coverage. Run it yourself
// after touching merge.ts:
//
//     pnpm --filter @plane/workload-ext build && node verify-merge.mjs
//
// The two checks that matter most are "unscheduled not multiplied" and "merge
// is idempotent": both fail loudly if merging ever starts ADDING buckets
// instead of unioning them, which is the one way this cache can silently
// report wrong hours. Verified 2026-08-19 by temporarily switching mergeRow to
// sum — the idempotence check went red, then green again on revert.

import {
  normalizeRanges,
  subtractRanges,
  snapRangeToPeriods,
  periodKeyFor,
  packTasksIntoLanes,
  mergeWorkloadResponses,
  WorkloadStore,
  shiftDates,
  resizeStart,
  resizeEnd,
} from "./dist/index.mjs";

let fail = 0;
const eq = (name, got, want) => {
  const g = JSON.stringify(got),
    w = JSON.stringify(want);
  if (g !== w) {
    console.log(`FAIL ${name}\n  got  ${g}\n  want ${w}`);
    fail++;
  } else console.log(`PASS ${name}`);
};

// normalize: fuse adjacent + overlapping
eq(
  "normalize fuses adjacent",
  normalizeRanges([
    { from: "2026-01-01", to: "2026-01-05" },
    { from: "2026-01-06", to: "2026-01-09" },
  ]),
  [{ from: "2026-01-01", to: "2026-01-09" }]
);
eq(
  "normalize fuses overlapping",
  normalizeRanges([
    { from: "2026-01-01", to: "2026-01-10" },
    { from: "2026-01-05", to: "2026-01-20" },
  ]),
  [{ from: "2026-01-01", to: "2026-01-20" }]
);
eq(
  "normalize keeps a real gap",
  normalizeRanges([
    { from: "2026-01-01", to: "2026-01-05" },
    { from: "2026-01-08", to: "2026-01-09" },
  ]),
  [
    { from: "2026-01-01", to: "2026-01-05" },
    { from: "2026-01-08", to: "2026-01-09" },
  ]
);

// subtract: the core of "request only the gap"
eq(
  "fully covered -> nothing",
  subtractRanges({ from: "2026-01-02", to: "2026-01-04" }, [{ from: "2026-01-01", to: "2026-01-09" }]),
  []
);
eq("nothing covered -> whole", subtractRanges({ from: "2026-01-02", to: "2026-01-04" }, []), [
  { from: "2026-01-02", to: "2026-01-04" },
]);
eq(
  "pan right -> only new tail",
  subtractRanges({ from: "2026-01-05", to: "2026-01-20" }, [{ from: "2026-01-01", to: "2026-01-10" }]),
  [{ from: "2026-01-11", to: "2026-01-20" }]
);
eq(
  "pan left -> only new head",
  subtractRanges({ from: "2026-01-01", to: "2026-01-10" }, [{ from: "2026-01-05", to: "2026-01-20" }]),
  [{ from: "2026-01-01", to: "2026-01-04" }]
);
eq(
  "hole in the middle",
  subtractRanges({ from: "2026-01-01", to: "2026-01-20" }, [
    { from: "2026-01-01", to: "2026-01-05" },
    { from: "2026-01-15", to: "2026-01-20" },
  ]),
  [{ from: "2026-01-06", to: "2026-01-14" }]
);

// period keys + snapping (Monday start = 1)
eq("week key of a Tuesday", periodKeyFor("2026-08-18", "week", 1), "2026-08-17");
eq("month key", periodKeyFor("2026-08-18", "month", 1), "2026-08");
eq("day key is itself", periodKeyFor("2026-08-18", "day", 1), "2026-08-18");
eq("snap week outward", snapRangeToPeriods({ from: "2026-08-18", to: "2026-08-20" }, "week", 1), {
  from: "2026-08-17",
  to: "2026-08-23",
});
eq("snap month outward", snapRangeToPeriods({ from: "2026-08-18", to: "2026-09-02" }, "month", 1), {
  from: "2026-08-01",
  to: "2026-09-30",
});
eq("snap day is identity", snapRangeToPeriods({ from: "2026-08-18", to: "2026-08-20" }, "day", 1), {
  from: "2026-08-18",
  to: "2026-08-20",
});

// merge: union, never addition; unscheduled must not multiply
const mk = (periods, buckets, tasks, unsched) => ({
  granularity: "day",
  date_from: periods[0],
  date_to: periods[periods.length - 1],
  periods,
  rows: [
    {
      assignee_id: "u1",
      assignee_name: "u",
      buckets,
      capacity_buckets: Object.fromEntries(periods.map((p) => [p, 8])),
      over: {},
      total: Object.values(buckets).reduce((a, b) => a + b, 0),
      total_over: false,
      tasks,
      tasks_truncated: false,
    },
  ],
  unscheduled: [{ assignee_id: "u1", hours: unsched }],
  meta: {
    issues_counted: 1,
    issues_unscheduled: 0,
    dirty_date_count: 0,
    zero_estimate_count: 0,
    unscheduled_ratio: 0,
    truncated: false,
  },
});
const a = mk(["2026-01-01"], { "2026-01-01": 5 }, [{ id: "t1" }], 12);
const b = mk(["2026-01-02"], { "2026-01-02": 3 }, [{ id: "t1" }, { id: "t2" }], 12);
const m = mergeWorkloadResponses(a, b);
eq("merged buckets union", m.rows[0].buckets, { "2026-01-01": 5, "2026-01-02": 3 });
eq("merged total recomputed", m.rows[0].total, 8);
eq("boundary task deduped", m.rows[0].tasks.map((t) => t.id).toSorted(), ["t1", "t2"]);
eq("unscheduled not multiplied", m.unscheduled[0].hours, 12);
eq("periods union", m.periods, ["2026-01-01", "2026-01-02"]);
// idempotence: merging the same window twice must not change anything
eq("merge is idempotent", mergeWorkloadResponses(m, b).rows[0].total, 8);

// --- row order after a merge -------------------------------------------------
// The board is ordered by the SERVER (service.py `compute_workload`): Unassigned
// first, then case-insensitively by name. The merge must reproduce that order
// rather than invent its own, or the swimlanes re-shuffle the moment the reader
// scrolls far enough to trigger a second fetch.
//
// This regressed silently for months: the merge sorted by `total` DESCENDING,
// left over from before #46 moved the server to alphabetical. A first paint has
// no base to merge against, so it looked right until you scrolled.
const rowOf = (id, name, total) => ({
  assignee_id: id,
  assignee_name: name,
  buckets: { "2026-01-01": total },
  capacity_buckets: { "2026-01-01": 8 },
  month_buckets: { "2026-01": total },
  over: {},
  total,
  total_over: false,
  tasks: [],
  tasks_truncated: false,
});
const withRows = (rows) => ({
  granularity: "day",
  date_from: "2026-01-01",
  date_to: "2026-01-01",
  periods: ["2026-01-01"],
  rows,
  unscheduled: [],
  meta: {
    issues_counted: rows.length,
    issues_unscheduled: 0,
    dirty_date_count: 0,
    zero_estimate_count: 0,
    unscheduled_ratio: 0,
    truncated: false,
  },
});
// Deliberately adversarial: the busiest member sorts LAST alphabetically, and
// the lightest sorts first. A `total`-descending sort produces the exact reverse
// of the right answer, so this cannot pass by coincidence.
// Tag with the id as well: two rows can legitimately share the display name
// "Unassigned", and a name-only projection cannot tell their order apart —
// which would let a wrong order pass as right.
const orderNames = (res) => res.rows.map((r) => `${r.assignee_name}#${r.assignee_id ?? "null"}`);
eq(
  "merge orders rows alphabetically, not by hours",
  orderNames(
    mergeWorkloadResponses(
      withRows([rowOf("u3", "zoe", 40), rowOf("u1", "alice", 1)]),
      withRows([rowOf("u2", "Bob", 20)])
    )
  ),
  ["alice#u1", "Bob#u2", "zoe#u3"]
);
eq(
  "merge keeps Unassigned first regardless of hours",
  orderNames(mergeWorkloadResponses(withRows([rowOf("u1", "alice", 99)]), withRows([rowOf(null, "Unassigned", 1)]))),
  ["Unassigned#null", "alice#u1"]
);
eq(
  "a real member named Unassigned still sorts under U",
  orderNames(
    mergeWorkloadResponses(
      withRows([rowOf(null, "Unassigned", 1), rowOf("u9", "Unassigned", 50)]),
      withRows([rowOf("u1", "alice", 2)])
    )
  ),
  ["Unassigned#null", "alice#u1", "Unassigned#u9"]
);

// lane packing: fewest rows such that no two bars in a row overlap
const T = (id, start, target) => ({ id, start_date: start, target_date: target });
const ids = (lanes) => lanes.map((l) => l.map((t) => t.id));

eq(
  "disjoint tasks share one lane",
  ids(packTasksIntoLanes([T("a", "2026-01-01", "2026-01-02"), T("b", "2026-01-05", "2026-01-06")])),
  [["a", "b"]]
);
eq(
  "overlapping tasks split lanes",
  ids(packTasksIntoLanes([T("a", "2026-01-01", "2026-01-10"), T("b", "2026-01-05", "2026-01-06")])),
  [["a"], ["b"]]
);
eq(
  "adjacent counts as collision",
  ids(packTasksIntoLanes([T("a", "2026-01-01", "2026-01-05"), T("b", "2026-01-05", "2026-01-07")])),
  [["a"], ["b"]]
);
eq(
  "lane count equals max concurrency",
  packTasksIntoLanes([
    T("a", "2026-01-01", "2026-01-10"),
    T("b", "2026-01-02", "2026-01-09"),
    T("c", "2026-01-03", "2026-01-08"),
  ]).length,
  3
);
eq(
  "first-fit reuses the earliest free lane",
  ids(
    packTasksIntoLanes([
      T("a", "2026-01-01", "2026-01-10"),
      T("b", "2026-01-02", "2026-01-03"),
      T("c", "2026-01-05", "2026-01-06"),
    ])
  ),
  [["a"], ["b", "c"]]
);
eq(
  "unscheduled tasks are never placed",
  ids(packTasksIntoLanes([T("a", "2026-01-01", null), T("b", "2026-01-05", "2026-01-06")])),
  [["b"]]
);
eq(
  "target-only task occupies its single day",
  ids(packTasksIntoLanes([T("a", null, "2026-01-05"), T("b", "2026-01-05", "2026-01-06")])),
  [["a"], ["b"]]
);
eq(
  "input array is not mutated",
  (() => {
    const input = [T("z", "2026-01-09", "2026-01-09"), T("a", "2026-01-01", "2026-01-02")];
    packTasksIntoLanes(input);
    return input.map((t) => t.id);
  })(),
  ["z", "a"]
);
eq(
  "a long bar keeps its lane busy past a later short one",
  ids(
    packTasksIntoLanes([
      T("long", "2026-01-01", "2026-01-20"),
      T("mid", "2026-01-02", "2026-01-03"),
      T("late", "2026-01-10", "2026-01-11"),
    ])
  ),
  [["long"], ["mid", "late"]]
);

// patchTaskDates / rollbackTaskDates: the per-task date-mutation seam (phase 1).
// Dates below are deliberately far in the past ("1990-…") or far in the future
// ("2999-…") rather than relative to "today" — the overdue recompute reads the
// REAL wall clock, and a fixture using dates near the actual test-run date
// would make the past/future assertions flaky depending on when this script
// runs.
const sharedTask = (overrides) => ({
  id: "shared-1",
  project_id: "proj-1",
  identifier: "ENG-1",
  name: "Shared task",
  hours: 4,
  total_hours: 8,
  assignee_count: 2,
  start_date: "1990-06-10",
  target_date: "1990-06-15",
  state_group: "started",
  overdue: false, // irrelevant seed value — patchTaskDates always recomputes it
  ...overrides,
});
const taskRow = (assigneeId, assigneeName, tasks) => ({
  assignee_id: assigneeId,
  assignee_name: assigneeName,
  buckets: { "2026-01-01": 5 },
  capacity_buckets: { "2026-01-01": 8 },
  over: {},
  total: 5,
  total_over: false,
  tasks,
  tasks_truncated: false,
});
const buildFixture = () => ({
  granularity: "day",
  date_from: "2026-01-01",
  date_to: "2026-01-01",
  periods: ["2026-01-01"],
  rows: [
    taskRow("u1", "alice", [sharedTask({})]),
    taskRow("u2", "bob", [sharedTask({})]),
    taskRow("u3", "carol", [
      { ...sharedTask({}), id: "solo-1", identifier: "ENG-2", name: "Solo task", assignee_count: 1 },
    ]),
  ],
  unscheduled: [],
  meta: {
    issues_counted: 3,
    issues_unscheduled: 0,
    dirty_date_count: 0,
    zero_estimate_count: 0,
    unscheduled_ratio: 0,
    truncated: false,
  },
});

const store = new WorkloadStore();
store.workloadData = buildFixture();
// Captured from `store.workloadData`, not the raw fixture: `workloadData` is a
// MobX deep-observable field, so the store's own copy is a wrapped object
// distinct from the plain object that was assigned to it. Comparing against
// the raw fixture would make every identity assertion below vacuously true —
// the baseline has to come from the same observable graph the post-patch
// reads come from.
const workloadDataBefore = store.workloadData;
const untouchedRow = workloadDataBefore.rows[2];
const sharedRowBuckets = workloadDataBefore.rows[0].buckets;

const snapshot = store.patchTaskDates("shared-1", { start_date: "2999-01-01", target_date: "2999-01-05" });

eq("patchTaskDates returns the pre-patch snapshot", snapshot, {
  issueId: "shared-1",
  start_date: "1990-06-10",
  target_date: "1990-06-15",
});
eq(
  "patchTaskDates updates the task on every row it appears on",
  store.workloadData.rows
    .slice(0, 2)
    .map((r) => r.tasks.find((t) => t.id === "shared-1"))
    .map((t) => [t.start_date, t.target_date]),
  [
    ["2999-01-01", "2999-01-05"],
    ["2999-01-01", "2999-01-05"],
  ]
);
eq("patchTaskDates replaces workloadData with a new object", store.workloadData !== workloadDataBefore, true);
eq(
  "patchTaskDates leaves a row with no matching task referentially unchanged",
  store.workloadData.rows[2] === untouchedRow,
  true
);
eq(
  "patchTaskDates flips overdue to false when a past-due task is moved into the future",
  store.workloadData.rows[0].tasks.find((t) => t.id === "shared-1").overdue,
  false
);
eq(
  "patchTaskDates leaves buckets/capacity_buckets/total untouched (same reference, same value)",
  store.workloadData.rows[0].buckets === sharedRowBuckets && store.workloadData.rows[0].total === 5,
  true
);
eq(
  "patchTaskDates leaves a terminal-state task never-overdue even when moved into the past",
  (() => {
    const s2 = new WorkloadStore();
    s2.workloadData = { ...buildFixture(), rows: [taskRow("u1", "alice", [sharedTask({ state_group: "completed" })])] };
    s2.patchTaskDates("shared-1", { start_date: "1980-01-01", target_date: "1980-01-05" });
    return s2.workloadData.rows[0].tasks[0].overdue;
  })(),
  false
);

// Move the same task into the past to exercise the other overdue flip, then
// roll back to the ORIGINAL snapshot (captured before either patch) and
// confirm every occurrence is restored — not just the most recent patch.
store.patchTaskDates("shared-1", { start_date: "1980-01-01", target_date: "1980-01-05" });
eq(
  "patchTaskDates flips overdue to true when a future task is moved into the past",
  store.workloadData.rows[0].tasks.find((t) => t.id === "shared-1").overdue,
  true
);
store.rollbackTaskDates(snapshot);
eq(
  "rollbackTaskDates restores the pre-patch dates on every occurrence",
  store.workloadData.rows
    .slice(0, 2)
    .map((r) => r.tasks.find((t) => t.id === "shared-1"))
    .map((t) => [t.start_date, t.target_date]),
  [
    ["1990-06-10", "1990-06-15"],
    ["1990-06-10", "1990-06-15"],
  ]
);
eq(
  "rollbackTaskDates recomputes overdue for the restored (past) dates",
  store.workloadData.rows[0].tasks.find((t) => t.id === "shared-1").overdue,
  true
);

// shiftDates / resizeStart / resizeEnd: the task-bar drag/resize date algebra
// (phase 2's three pure functions, moved into dateRange.ts per phase 6 so this
// script can assert them with no DOM). Dates use the same "far past / far
// future" idiom as the patchTaskDates fixtures above, for the same reason —
// none of this arithmetic reads the wall clock, so there is nothing to gain
// and a same-year fixture risks becoming date-sensitive by accident later.

// move — zero-day shift returns the SAME dates unchanged, start_date included
// (not "start_date coerced to target_date"), because a zero-pixel drag on a
// null-start task must not manufacture a "changed" result out of a no-op.
eq(
  "shiftDates: zero-day shift is a no-op, null start_date preserved",
  shiftDates({ start_date: null, target_date: "2026-03-10" }, 0),
  { start_date: null, target_date: "2026-03-10" }
);
eq(
  "shiftDates: null start_date materializes at the new target on a real move",
  shiftDates({ start_date: null, target_date: "2026-03-10" }, 3),
  { start_date: "2026-03-13", target_date: "2026-03-13" }
);
eq(
  "shiftDates: a single-day task (start === target) keeps zero duration after a move",
  shiftDates({ start_date: "2026-03-10", target_date: "2026-03-10" }, 5),
  { start_date: "2026-03-15", target_date: "2026-03-15" }
);
eq(
  "shiftDates: both dates move by the same day count, duration preserved",
  shiftDates({ start_date: "2026-03-01", target_date: "2026-03-05" }, -2),
  { start_date: "2026-02-27", target_date: "2026-03-03" }
);

// resize-start — clamp collision: dragging the left edge PAST (or onto) the
// right edge stops one day short of target rather than swapping the dates.
eq(
  "resizeStart: ordinary drag left of target_date is unclamped",
  resizeStart({ start_date: "2026-03-05", target_date: "2026-03-10" }, "2026-03-02"),
  { start_date: "2026-03-02", target_date: "2026-03-10" }
);
eq(
  "resizeStart: dragging exactly onto target_date reaches it — a valid one-day task, not a clamp",
  resizeStart({ start_date: "2026-03-05", target_date: "2026-03-10" }, "2026-03-10"),
  { start_date: "2026-03-10", target_date: "2026-03-10" }
);
eq(
  "resizeStart: dragging past target_date clamps AT target_date (a one-day task), not one day short",
  resizeStart({ start_date: "2026-03-05", target_date: "2026-03-10" }, "2026-03-20"),
  { start_date: "2026-03-10", target_date: "2026-03-10" }
);
eq(
  "resizeStart: a single-day task's left handle can stay at start === target — no forced clamp",
  resizeStart({ start_date: "2026-03-10", target_date: "2026-03-10" }, "2026-03-10"),
  { start_date: "2026-03-10", target_date: "2026-03-10" }
);
eq(
  "resizeStart: null start_date materializes directly at newStart when unclamped",
  resizeStart({ start_date: null, target_date: "2026-03-10" }, "2026-03-04"),
  { start_date: "2026-03-04", target_date: "2026-03-10" }
);

// resize-end — mirror clamp, and the "only when a start exists" carve-out.
eq(
  "resizeEnd: ordinary drag right of start_date is unclamped",
  resizeEnd({ start_date: "2026-03-05", target_date: "2026-03-10" }, "2026-03-15"),
  { start_date: "2026-03-05", target_date: "2026-03-15" }
);
eq(
  "resizeEnd: dragging exactly onto start_date reaches it — a valid one-day task, not a clamp",
  resizeEnd({ start_date: "2026-03-05", target_date: "2026-03-10" }, "2026-03-05"),
  { start_date: "2026-03-05", target_date: "2026-03-05" }
);
eq(
  "resizeEnd: dragging before start_date clamps AT start_date (a one-day task), not one day past",
  resizeEnd({ start_date: "2026-03-05", target_date: "2026-03-10" }, "2026-02-20"),
  { start_date: "2026-03-05", target_date: "2026-03-05" }
);
eq(
  "resizeEnd: a single-day task's right handle can stay at target === start — no forced clamp",
  resizeEnd({ start_date: "2026-03-10", target_date: "2026-03-10" }, "2026-03-10"),
  { start_date: "2026-03-10", target_date: "2026-03-10" }
);
eq(
  "resizeEnd: null start_date is left untouched (unclamped) — only move/resize-start ever materialize it",
  resizeEnd({ start_date: null, target_date: "2026-03-10" }, "2026-03-20"),
  { start_date: null, target_date: "2026-03-20" }
);

// Direct regression pin for the live bug report: shrinking a 2-day task
// (start, start+1) down to a 1-day task (start === target) via EITHER
// handle. Before this fix both clamps used `>=`/`<=` and stopped one day
// short of the boundary instead of AT it, so the drag that should have
// produced a 1-day task silently kept producing a 2-day one — read by the
// user as "shrink from 2 days to 1 day doesn't work".
eq(
  "resizeEnd: shrinking a 2-day task (start, start+1) down to 1 day via the right handle",
  resizeEnd({ start_date: "2026-03-09", target_date: "2026-03-10" }, "2026-03-09"),
  { start_date: "2026-03-09", target_date: "2026-03-09" }
);
eq(
  "resizeStart: shrinking a 2-day task (target-1, target) down to 1 day via the left handle",
  resizeStart({ start_date: "2026-03-09", target_date: "2026-03-10" }, "2026-03-10"),
  { start_date: "2026-03-10", target_date: "2026-03-10" }
);

console.log(fail ? `\n${fail} FAILED` : "\nall passed");
process.exit(fail ? 1 : 0);
