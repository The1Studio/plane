# Phase 4 — Workload adopts the core packer

**Goal:** workload stops carrying its own packing and its own per-lane labels. Depends on Phases
1 and 2. Parent: [`plan.md`](plan.md).

## Ownership

- `packages/workload-ext/src/merge.ts`, `verify-merge.mjs`
- `apps/web/core/components/workload/timeline/**`

## 4.1 — One packer, in core (D5)

Delete `packTasksIntoLanes` from `packages/workload-ext` and import the core helper instead. Port
its checks from `verify-merge.mjs` to wherever the core helper is tested — do not simply drop
them, since they pin the adjacency rule and the no-mutation rule that #43's falsification pass
proved were load-bearing (relaxing `<` to `<=` turned two red).

Workload's own `wl-lane:` block construction collapses too: with core packing at the row level,
workload emits one block per task again and lets core group them. The header (heat row) and
footer blocks stay as they are.

## 4.2 — Sidebar carries identity only (D2)

The lane labels added in #43 — `PROJ-12` for a single task, `N items` otherwise — are removed.
Lane rows render a blank spacer that preserves vertical alignment; the swimlane header keeps
avatar, member name and capacity badge.

The footer strip (`Unscheduled (N)` / `Overdue (N)`) is a per-member affordance rather than a work
item list, so it stays. If that reads as "work item list" to you, say so and it goes too.

Bars keep identifier + name + hours and remain the peek-panel click targets, so nothing about
item identity is lost — it moves from the column to the bar.

## 4.3 — The viewport loader must follow the sidebar

`syncViewport` computes the visible date range as `scrollLeft + SIDEBAR_WIDTH` .. `scrollLeft +
clientWidth`. Workload still HAS a sidebar, so this offset stays correct here — but it must now
be derived from the same single source Phase 2.2 introduces, not from the constant directly, or
the two will drift the first time sidebar width changes.

## Success criteria

- Exactly one lane-packing implementation exists in the repo.
- The workload board renders the same shape as after #43, minus the lane labels.
- `node packages/workload-ext/verify-merge.mjs` still green (range algebra + merge unaffected).
- The badge and heat cells still agree, and panning still loads the right range.
