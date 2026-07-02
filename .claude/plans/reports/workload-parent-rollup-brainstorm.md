# Brainstorm Report — Workload Parent Rollup (estimates, due date, progress %)

Date: 2026-07-02 · Session: brainstorm → approved → implement
Feature owner app: `apps/api/plane/workload/` + `packages/workload-ext/`

## Problem statement

1. **Double-counting:** parent issue and its children can each carry a `WorkloadEstimate`;
   `aggregation.py` is parent-blind → matrix shows parent 10h + children 10h = 20h.
2. **Drifting parent dates:** parent `target_date` is manual, not derived from children.
3. **No hours-weighted progress:** core Plane only has count-based sub-issue progress
   (`sub_issues_count`, `state_distribution` in `app/views/issue/sub_issue.py`). No notion of
   "60% of estimated hours finished".

## Decided semantics (user answers, AskUserQuestion 2026-07-02)

| Decision                                  | Choice                                                                                            |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Parent estimate enforcement               | **Hard block** — API rejects PUT on issues with children; UI read-only rollup                     |
| Stored estimate when issue becomes parent | **Keep but ignore** — resurfaces if all children removed                                          |
| Due date                                  | **Display-only rollup** in fork surfaces (`max(child target_date)`); core `target_date` untouched |
| Rollup depth                              | **Full tree** (recursive over descendants, leaves carry the hours)                                |
| Cancelled children                        | **Excluded** from rollup (and archived/deleted/draft, matching matrix predicate)                  |
| Progress %                                | **Hours-weighted:** Σ hours of completed-group leaves ÷ Σ hours of countable leaves               |

## Approaches evaluated

|             | A. Compute-on-read (recursive CTE) ✅ | B. Materialized rollup table + signals           | C. Frontend-computed          |
| ----------- | ------------------------------------- | ------------------------------------------------ | ----------------------------- |
| Freshness   | always correct                        | sync bugs (parent moves, bulk ops, cascades)     | needs backend endpoint anyway |
| Fork safety | new code only                         | signals hook core Issue writes — rebase coupling | matrix fix still backend      |
| Rules fit   | matches No-Derived-Fields SSOT        | violates it (no perf evidence at 50-user scale)  | splits truth across layers    |

**Chosen: A.** Depth-capped (10), cycle-safe recursive CTE; milliseconds at this scale.

## Design

**Backend** (`plane/workload/` only, no core edits):

- Shared "countable issue" predicate (not deleted/archived/draft; excl. cancelled state group for rollup) — one function used by matrix + rollup (SSOT).
- `rollup.py`: recursive descendants CTE → per-parent `{hours, due_date, done_hours, percent, leaf_count}`. Leaf = countable descendant with no countable children. `percent = done_hours/hours` (null when hours=0).
- PUT estimate: issue has countable children → `400 {"error_code": "PARENT_HAS_CHILDREN"}`.
- Matrix aggregation: count leaf issues only → kills double-counting.
- GET single + bulk: add `is_parent`; for parents add `rollup` object.

**Frontend** (`workload-ext` + existing fork surfaces): parents render read-only `Σ Xh · N%` (tooltip: from N sub-items · due <date>); estimate input disabled with explanation. Progress % shown alongside.

**Propagation** (standing rule): issues on `plane-mcp-server` (new 400 + rollup in reads), `plane-node-sdk`, `plane-python-sdk`, docs; CLAUDE.md Custom-features line.

## Risks / notes

- Middle nodes (child AND parent) contribute no own hours — correct; document.
- Legacy parent estimates resurface when all children deleted — decided behavior.
- CTE needs depth cap + guard consistent with existing `aggregation.py` caps.
- "Completed" = state group `completed` (matches core semantics); cancelled excluded entirely.
- Day-1: parents show "—" until children get estimates (no backfill).

## Next step

Phased plan: `.claude/plans/workload-parent-rollup-plan.md`, validated in 5 adversarial rounds before implementation (user request).
