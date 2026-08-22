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
  orderNames(
    mergeWorkloadResponses(
      withRows([rowOf("u1", "alice", 99)]),
      withRows([rowOf(null, "Unassigned", 1)])
    )
  ),
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

console.log(fail ? `\n${fail} FAILED` : "\nall passed");
process.exit(fail ? 1 : 0);
