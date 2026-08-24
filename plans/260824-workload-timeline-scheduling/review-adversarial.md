# Adversarial Code Review — workload timeline scheduling (phases 1–6)

**Scope:** the full uncommitted diff on `feat/workload-timeline-scheduling` vs `company-main@e460d3094e`
(857 insertions / 132 deletions across 7 tracked files + 2 new untracked components).
**Reviewed against:** `plan.md` D1–D11 + risk table, and each `phase-N.md` as acceptance criteria.

## Invariants — all held

| Claim                         | Evidence                                                                                                                                                                                                                      |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No backend edit               | `git diff company-main --stat -- apps/api/` → empty                                                                                                                                                                           |
| No core gantt edit            | `… -- apps/web/core/components/gantt-chart/` → empty                                                                                                                                                                          |
| No issue-modal edit           | `… -- apps/web/core/components/issues/` → empty                                                                                                                                                                               |
| `docs/FORK.md` untouched      | `… -- docs/FORK.md` → empty                                                                                                                                                                                                   |
| Nothing outside the owned set | only `workload/timeline/*`, `packages/workload-ext/*`, `CLAUDE.md` (gitignored, verified by grep — the `workload/` bullet carries drag/resize, the no-new-endpoint statement, the `0h` bar note and the heat-cell lag caveat) |
| `verify-merge.mjs` green      | `pnpm build && node verify-merge.mjs` → 18 new PASS, `all passed`                                                                                                                                                             |

The phase-6 `dateRange.ts` move is correct and complete: `shiftDates`/`resizeStart`/`resizeEnd` are
exported from `@plane/workload-ext`, `useTaskBarDrag.ts:22` re-imports them cleanly, and nothing
else referenced them at their old home.

---

## Blocking

### B1 — the left resize handle unmounts _while it is being dragged_, stranding the drag permanently

`WorkloadTimelineChartBlock.tsx` (`showLeftHandle`), with `useTaskBarDrag.ts:175,259-263`.

`showLeftHandle = canEdit && width - 2 * HANDLE_WIDTH_PX >= MIN_BODY_WITH_BOTH_HANDLES_PX`, and
during a drag `width` is the **preview** width, which deliberately does _not_ apply
`MIN_BAR_WIDTH`. At quarter zoom (`dayWidth = 30`) a one-day preview is 30px → `30 − 12 = 18 < 24`
→ React unmounts the very handle the pointer is on.

The hook binds `pointermove`/`pointerup`/`pointercancel` to `element = e.currentTarget` (that
handle) and holds `setPointerCapture` on it. Once it leaves the DOM:

- no `pointerup` ever reaches `handlePointerUp`, so `cleanup()` never runs;
- `dragStateRef.current` stays non-null → `if (dragStateRef.current) return` (line 173) blocks
  **every future drag on that bar**;
- `preview` stays non-null → the bar is frozen at the preview geometry;
- `isDragging` / `suppressClick` stay `true` → the bar also stops opening the peek panel.

Only a remount (filter or zoom change) recovers. D5 explicitly says "no zoom is excluded", so
quarter zoom is in scope.

**Fix:** derive handle visibility from the committed width
(`Math.max(endPos - startPos, MIN_BAR_WIDTH)`), never from `width`; or force
`showLeftHandle || isDragging`. A `pointercancel`-independent safety net in the hook (an unmount
guard that also releases capture) would harden it further.

### B2 — the `+` affordance is drawn on the wrong day for the right half of every column

`WorkloadCreateOverlay.tsx:65,68,76` vs `gantt-chart/views/helpers.ts:74`.

The button snaps with `Math.floor(hoverX / dayWidth) * dayWidth`; the date comes from
`getDateFromPositionOnGantt`, which uses `Math.round(position / dayWidth)`. Past a column's
midpoint the tooltip and the created work item advance to day _N+1_ while the `+` stays centred on
day _N_. Clicking the button's own centre (`columnLeft + dayWidth / 2`) rounds **up**, so the
common gesture — click the `+` you can see — reliably creates on the following day.

Fails phase 5's success criterion "a `+` snapped to a day column, with the correct date".

**Fix:** derive the column from the same rounding the date uses, e.g.
`Math.round((hoverX + laneMarginLeft) / dayWidth) * dayWidth − laneMarginLeft`.

### B3 — the date tooltip on the `+` can never open

`WorkloadCreateOverlay.tsx:88-99`, with `packages/propel/src/tooltip/root.tsx:55`.

`Tooltip` renders `<BaseTooltip.Trigger render={children}>`, which merges its hover/focus handlers
onto **the button itself** — and that button is `pointer-events-none` (and `tabIndex={-1}`). A
`pointer-events: none` element is never a hit-test target, so no pointer or focus event ever
reaches the trigger and the tooltip never shows. The user sees a bare `+` with no date.

The `pointer-events-none` is load-bearing for `offsetX` correctness (the comment at lines 71-75 is
right about that), so the tooltip has to move rather than the class.

**Fix:** attach the tooltip to the overlay `div`, or render the date as inline text beside the `+`.

---

## Important

### I1 — click-to-create only reaches the _gaps between_ a member's existing bars

`WorkloadTimelineChartBlock.tsx` mounts the overlay as `absolute inset-0` inside the lane block's
box, and a lane block spans exactly `laneStart` → `laneEnd` (`blocks.ts:156-167`) — the first
task's start to the latest target. Consequences:

- no overlay before the first bar or after the last one;
- a member with **no tasks at all** has no lane block, therefore no overlay, therefore no way to
  create work for them from this board.

That last case is the one the plan's own Problem statement names ("no way to put new work onto a
member's lane from here at all"). Either widen the overlay to the row's full width or record this
as an explicit documented limitation the way D3's heat-cell lag is.

### I2 — Escape aborts the drag, then the trailing click opens the peek panel anyway

`useTaskBarDrag.ts:254-257` → `finishDrag(false, false)` → lines 220-223 reset `suppressClick` to
`false` and arm no swallow listener. But the pointer button is still down; the eventual `pointerup`
synthesises a `click` on the bar, `WorkloadTaskLink` sees `suppressClick === false`, and the peek
panel opens. Phase 2's "a drag begun by accident costs nothing" is not met — it costs a peek panel,
which is exactly the outcome D6 exists to prevent.

**Fix:** Escape should still arm the swallow (`finishDrag(false, true)`), or the hook should track
"pointer still down" and defer the `suppressClick` reset to the real `pointerup`.

### I3 — a skipped synthesised click leaves the bar unclickable and then eats the next real click

`useTaskBarDrag.ts:228-237`. The comment claims that if no click arrives the once-listener "is
simply inert, at the cost of one stray handler". It is not inert: `{ once: true }` keeps it armed,
so it swallows the **next** click on that bar, and `suppressClick` stays `true` in React state in
the meantime so `WorkloadTaskLink` blocks that click too. Net effect: one silently lost peek-panel
open per occurrence, with a misleading comment pointing the next reader away from it.

**Fix:** clear `suppressClick` on the next `pointerdown` on that bar, and/or fall back to a
`setTimeout(0)`/`requestAnimationFrame` disarm.

---

## Minor

- **M1 — `preventDefault` runs for read-only bars too.** `handleBodyPointerDown` calls
  `e.preventDefault()` before the hook's `if (disabled) return`. On mouse this suppresses focusing
  the anchor (a bar can no longer be focused by clicking — an a11y regression against the previous
  plain `ControlLink`); on touch it can suppress panning of the chart. Gate the `preventDefault` on
  `canEdit`.
- **M2 — a stable prop became an inline lambda.** `WorkloadTimelineRoot.tsx` replaced the
  module-scope `noopBlockUpdateHandler` with `blockUpdateHandler={(_b, _p) => {}}`, giving
  `GanttChartRoot` a new prop identity on every render of an observer that re-renders on every
  store change. Phase 4 asked for the constant to be _deleted_, not inlined; keep a module-scope
  no-op.
- **M3 — the synthetic snapshot carries the NEW dates as the "before".** `store.ts:328`:
  `return snapshot ?? { issueId, start_date: dates.start_date, target_date: dates.target_date }`.
  Harmless _today_ only because `rollbackTaskDates` no-ops under exactly the same conditions that
  produced the synthetic value — but if `workloadData` repopulates between the patch and a rejected
  response, the rollback re-applies the failed dates as if they were the original. Prefer
  `TTaskDatesSnapshot | null` and let the caller skip.
- **M4 — a miss still costs a full-viewport refetch.** `store.ts:326-327` clears `loadedRanges` and
  bumps `coverageVersion` even when `_applyTaskDates` matched nothing.
- **M5 — the overlay's header comment contradicts its own code.** It states "neither this layer nor
  a bar sets a z-index" (`WorkloadCreateOverlay.tsx:9-14`) while the layer is `z-0` and the handles
  are `z-10`. The behaviour is still correct (`z-0` and `z-auto` paint in the same tree-order
  group), but the stated reason is wrong — the kind of comment a future reader "fixes" in the wrong
  direction.
- **M6 — a left-edge drag on a single-day task moves the start backwards.** `resizeStart` clamps
  `newStart >= target` to `target − 1`, which for `start === target` is one day _earlier_ than the
  current start: dragging the left edge right makes the bar longer. Literally D7-conformant and
  asserted in `verify-merge.mjs`, but the gesture reads as broken. Consider returning the dates
  unchanged when `start === target`.
- **M7 — zero-width preview at the chart's first day.** `getPositionFromDate` returns `0` and drops
  `offsetWidth` when the date equals the chart start (`helpers.ts:132`), so `previewFromDates`'
  right edge collapses for a bar whose `target_date` is the chart's first day. Pre-existing core
  quirk, newly depended on by the preview path.
- **M8 — a11y.** The resize handles are `tabIndex={0}` `div`s with no `role` and no keyboard
  handler: focusable but not operable (WCAG 2.1.1). The overlay is a `div` with `onClick`, no
  `role`/keyboard path, and drives its affordance from `onMouseMove` only — so click-to-create is
  mouse-only and the `+` never appears on touch.

---

## Nits

- `.diskcheck-tmp` (3.5 KB, untracked, repo root) — unrelated to this work; do not let it into the
  commit.
- Phase 6 required _proving_ an assertion can fail ("temporarily break `patchTaskDates`… confirm
  the check goes red"). No evidence of that is recorded. With no CI job behind `verify-merge.mjs`,
  an unproven green is precisely the failure `green-that-proves-nothing.md` describes — record the
  deliberate-break result in the PR body.
- `seedData` is rebuilt on every root render. Harmless: `IssueFormRoot`'s data-reset effect keys on
  `dataResetProperties`, which defaults to `[]`, so the form resets on mount only. Noted so the next
  reader does not have to re-derive it.

---

## Claims checked and found NOT to be defects

Worth recording, because several are the obvious first suspicions:

- **Timezone / UTC off-by-one on drag or create — does not occur.** `getDate` builds
  `new Date(y, m-1, d)` (local), `addDaysToDate` copies and uses `setDate` (local, DST-safe), and
  `renderFormattedPayloadDate` formats with date-fns `format(…, "yyyy-MM-dd")` (local). The
  `getPositionFromDate` → `getDateFromPositionOnGantt` round-trip is consistent in every offset.
  `shiftDate` (local parse) and `daysBetween` (UTC parse, difference only) are each correct for
  their own job.
- **`offsetX` measured against a child element — cannot happen here.** Base UI's `Tooltip.Trigger`
  uses `render={children}` and adds no wrapper node, and the only child is `pointer-events-none`.
  (This is also what makes B3 true.)
- **Bars vs overlay paint order — correct.** The overlay is mounted first and `z-0`; the bars are
  later siblings at `z-auto`. Both fall in the same painting group, so tree order puts the bars on
  top and a click on a bar never reaches the overlay.
- **`lastSnappedDeltaPx !== 0` skipping a commit after a there-and-back drag — correct, not a
  silent divergence.** Nothing was optimistically patched either, so the client and server agree.
- **Concurrent-drag rollback guard — sound.** `taskDatesStillMatch` compares the store's _current_
  dates against the dates _this_ patch wrote, so a later drag's result survives an earlier drag's
  failure. It satisfies phase 4's requirement even though `TTaskDatesSnapshot` carries only the
  "before" half; the "after" comes from the closure. `_fetchGap`'s `requestedVersion` check
  continues to discard responses that predate the patch.
- **Unmounted-setState warnings — not present.** `cleanup` only removes listeners and nulls the
  ref; it calls no setter.
- **`patchTaskDates` object identity — correct.** New top-level object and new row objects only for
  changed rows; untouched rows keep their reference (asserted).

---

## Decision conformance

| #                                                         | Verdict                                                                                  |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| D1 fork-owned per-bar drag, core `enableBlock*` off       | ✅ all five flags still `false`                                                          |
| D2 unmodified `CreateUpdateIssueModal`, no estimate field | ✅ zero diff under `issues/issue-modal/`                                                 |
| D3 optimistic patch + narrow invalidation                 | ✅ `loadedRanges = []` + `coverageVersion += 1`                                          |
| D4 per-bar `MEMBER`/`ADMIN` on the bar's own `project_id` | ✅ `WorkloadTaskBar` calls `allowPermissions(…, PROJECT, slug, task.project_id)` per bar |
| D5 day snapping at every zoom                             | ⚠️ snapping is right, but quarter zoom is exactly where **B1** bites                     |
| D6 4px threshold, drag never navigates                    | ⚠️ holds for the normal path; **I2**/**I3** are the two leaks                            |
| D7 duration preserved / clamped                           | ✅ (see **M6** for the single-day corner)                                                |
| D8 null `start_date` handling                             | ✅ asserted in `verify-merge.mjs`                                                        |
| D9 repack deferred to drop                                | ✅ store touched only in `onCommit`                                                      |
| D10 rollback + error toast, no success toast              | ✅                                                                                       |
| D11 no `resetCoverage()` after a drag                     | ✅ (used only on create-submit, as specified)                                            |

## Score: 7/10

Strong architecture — the seam between pure date algebra, the pointer hook, the permission gate and
the write path is exactly where the plan put it, the decisions are followed almost everywhere, and
the store work is genuinely well-tested for a repo with no frontend test job. What holds it back is
that the three affordances were each verified in their easy configuration: **B1** and **B2** both
live in geometry that only misbehaves off the default zoom or off the column midpoint, and **B3**
means one of phase 5's stated success criteria cannot have been executed as written.

**Recommend:** fix B1–B3 before opening the PR, decide I1 (widen or document), and land I2/I3 in the
same pass — all five are small, localised changes. The Minor list can follow.
