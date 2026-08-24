# Phase 6 — verify, document, and close the propagation question

**Owns:** `packages/workload-ext/verify-merge.mjs`, `CLAUDE.md`, `docs/FORK.md`
**Estimate:** 2h
**Depends on:** phases 1–5

## Goal

Leave behind evidence that the feature works, and a record of what it does, so the next reader does
not have to re-derive either.

## 1. Pure-function assertions

Extend `packages/workload-ext/verify-merge.mjs` — the existing hand-runnable script, whose own
header explains why a vitest suite here would be worse than nothing (this monorepo has no root
`test` script and no JS test job, so the suite would never run and would look like coverage).

Add two blocks:

- **Store seam** (phase 1's criteria): two-row patch, object-identity change, `overdue` recompute in
  both directions, rollback fidelity, and the assertion that `buckets` are untouched.
- **Date arithmetic** (phase 2's three exported functions): null `start_date`, single-day task,
  clamp collision in each direction, zero-day shift.

`useTaskBarDrag.ts` lives in `apps/web` and cannot be imported from this package's script. Either
move the three pure functions into `packages/workload-ext/src/` and import the hook's arithmetic from
there — which is the better home anyway, since they are date algebra with no React in them — or add
a second small script under `apps/web`. **Prefer the move**; one runnable script beats two.

Run: `pnpm --filter @plane/workload-ext build && node verify-merge.mjs`. Zero `FAIL` lines.

**Prove the assertions can fail.** Temporarily break one behaviour (make `patchTaskDates` patch only
the first matching row) and confirm the corresponding check goes red, then revert. An assertion never
seen failing is unproven, and this script has no CI job to catch a vacuous green.

## 2. Manual checklist

There is no frontend test job (`.github/workflows/company-main-ci.yml` runs `pnpm check` and
`pnpm turbo run build --filter=web` only), so pointer behaviour is verified by hand. Run the full
list before opening the PR and record the result in the PR body:

| #   | Check                                                       | Zoom           |
| --- | ----------------------------------------------------------- | -------------- |
| 1   | Plain click opens peek                                      | week           |
| 2   | 2px-jitter click opens peek                                 | week           |
| 3   | 40px drag moves the bar, no peek                            | week           |
| 4   | cmd-click opens the work item in a new tab                  | week           |
| 5   | Left handle moves start only; stops one day short of target | week           |
| 6   | Right handle moves target only; stops one day past start    | week           |
| 7   | Escape mid-drag aborts, bar returns                         | week           |
| 8   | Dates persist across a page reload                          | week           |
| 9   | Offline drag reverts the bar and toasts                     | week           |
| 10  | Guest-project bar has no handles and does not drag          | week           |
| 11  | Drag snaps in one-column steps                              | month, quarter |
| 12  | `+` appears on empty lane space with the right date         | all three      |
| 13  | Create lands as a bar in the right swimlane                 | week           |
| 14  | Collapsed swimlane shows no overlay and no handles          | month          |
| 15  | Heat cells under a moved bar update within ~1s              | week           |

Check 15 has a stated caveat, not a pass/fail: a period scrolled off-screen may lag until the next
full invalidation. That is the plan's documented limitation, and the checklist should say so rather
than letting a future reader read it as a flake.

## 3. Documentation

**`CLAUDE.md`** — extend the existing `workload/` bullet in "Custom features (fork-owned)". State,
in one place:

- bars are draggable and resizable on the timeline, gated per project at `MEMBER`/`ADMIN` on the
  bar's **own** project, so one swimlane can mix editable and read-only bars;
- a drag writes through the ordinary issue `PATCH` — **no new endpoint**, and a plain `PATCH` from
  any client behaves exactly as it did;
- clicking empty lane space opens the standard create modal pre-dated and pre-assigned, and the
  new item carries **no estimate**, so it renders as a `0h` bar until one is set;
- heat cells outside the current viewport may lag a drag until the next filter/zoom change or
  peek-panel close, and why.

That last point is the one a future reader is most likely to file as a bug. It belongs in the
feature entry, not only in this plan.

**`docs/FORK.md`** — no new core-edit exception row is owed, because this plan adds none. Confirm
that with a diff review rather than by assumption: `git diff --stat main...HEAD` must show nothing
under `apps/web/core/components/gantt-chart/`, nothing under
`apps/web/core/components/issues/issue-modal/`, and nothing under `apps/api/`. If any appears, a
decision was worked around and the row is owed — or, better, the edit should be removed.

## 4. Propagation

`CLAUDE.md`'s standing rule requires every new endpoint, field, or behaviour to reach the sibling
repos. Assessed here and **not owed**:

- rescheduling uses the existing issue `PATCH`, already exposed as MCP `update_work_item`;
- creation uses the existing issue-create path;
- no new field is returned by any workload endpoint;
- no serializer changed.

Record that conclusion explicitly in the `CLAUDE.md` entry. An absent propagation PR with no stated
reason is indistinguishable from a forgotten one.

## Success criteria

- `node verify-merge.mjs` clean, and one assertion demonstrated failing then restored.
- All 15 manual checks executed, results in the PR body.
- `pnpm check` and `pnpm turbo run build --filter=web` both clean.
- `git diff --stat` confirms the zero-core-edit claim.
- `CLAUDE.md` updated; `docs/FORK.md` confirmed unchanged with the diff as evidence.
