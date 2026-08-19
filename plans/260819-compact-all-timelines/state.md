# Handoff state — read this before touching anything

Written 2026-08-19 for an implementer starting cold, with no conversation history.
Everything below is fact-checked against the repo or against a live API response, not recalled.

## Where the code stands

Two PRs shipped TODAY and are **live in production** (`plane.the1studio.org`):

| PR                                                 | Squash commit | What                                                                                                                          |
| -------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| [#42](https://github.com/The1Studio/plane/pull/42) | `c0b85058d1`  | Weekly→viewport capacity badge, single time control, reference row layout, clickable work items, viewport-driven lazy loading |
| [#43](https://github.com/The1Studio/plane/pull/43) | `1578e2f835`  | Workload lane packing, 3× wider columns (ALL timelines), workload app header, dropdown stacking fix                           |

Both were **admin-merged unreviewed** (`gh pr merge --admin`) at the requester's explicit
instruction, after CI was confirmed green on the head commit. An active repository ruleset
(`Default`) requires 1 approving review on `company-main`; the author cannot self-approve, and
repo-level auto-merge is disabled. If you open a PR expecting it to merge on green, it will not —
it will sit at `mergeStateStatus: BLOCKED`, `reviewDecision: REVIEW_REQUIRED`.

This plan is on branch **`docs/plan-compact-all-timelines`** and is NOT merged. If you are on
`company-main` and cannot see `plans/260819-compact-all-timelines/`, that is why.

## What the workload timeline is now, architecturally

You will be changing code that #42/#43 rewrote. The three invariants that are easy to break:

1. **There is no date-range picker.** The chart's viewport IS the range.
   `WorkloadTimelineRoot.syncViewport` reads `#gantt-container`'s `scrollLeft`/`clientWidth`,
   converts to dates via `getDateFromPositionOnGantt`, and calls `store.ensureRange`. Debounced
   250ms. If you break this, the board loads nothing and looks like a data bug.
2. **Range merging is a key UNION, never an addition.** `packages/workload-ext/src/merge.ts`.
   Every fetched span is snapped OUTWARD to whole periods first, so a period key comes from
   exactly one fetch. Summing partial buckets from overlapping windows double-counts hours
   silently. `verify-merge.mjs`'s "merge is idempotent" check exists precisely to catch that;
   it was proven able to fail by switching the merge to sum.
3. **The chart is ALWAYS rendered; loading/empty/error are overlays.** An early return on "no
   data yet" DEADLOCKS the page: loading is viewport-driven, so a first paint that renders a
   placeholder never mounts `#gantt-container`, never measures a viewport, and never fetches.
   This was hit for real during #42.

## What has NEVER been verified

**Nothing in either PR has been confirmed on screen by anyone.** There is no browser in the
implementing environment. Type-checks, lint, backend tests and the merge verifier all pass, and
production API responses were checked directly — but the packed layout, the 3× columns, the
capacity badge, the app header and the dropdown stacking are all unconfirmed visually.

`PLANE-69` ("Verification gates and manual browser pass", Infrastructure ▸ Plane) is deliberately
left OPEN for this reason. Its eight checks are listed in
`plans/260818-workload-timeline-fixes/phase-5.md`. If you can open a browser, doing those first
is probably worth more than starting this plan.

## Loose ends someone should pick up

- **Six downstream propagation issues** are open and amended (they originally described
  `weekly_buckets`/`weekly_capacity`, which were then removed; each carries a retraction comment):
  `plane-mcp-server#14`, `plane-node-sdk#6`, `plane-python-sdk#6`, `plane-claude-plugin#4`,
  `docs#4`, `developer-docs#4`. All six surfaces are ALSO behind by `capacity_buckets`, `over`,
  `total_over`, `tasks`, `tasks_truncated` from earlier phases — the reports cover that too.
- **`total_over` changed VALUE, not definition**, once `periods` became window-complete. That is
  the one silent behavioural change for API consumers.
- **`plane-classify-path.cjs` misreports** `apps/web/core/components/workload/timeline/` as
  `core → relocate`, contradicting `docs/FORK.md`, which sanctions that directory. Pre-existing —
  the already-merged files classify the same way — but it will mislead anyone using the classifier
  to triage a rebase conflict there.
- **`i18n.ts` carries orphaned `matrix.*` keys** from the aggregate matrix deleted two phases ago.
  Harmless, left alone deliberately (pre-existing dead code is not in scope for an unrelated PR).

## Recommended first move

**Spike Phase 1 on the issue gantt before committing to Phases 2-5.**

The two-overlaid-row-lists discovery (see `phase-1.md` § 0) was found only by reading
`chart/main-content.tsx` directly — the plan's first draft missed it, and following that draft
would have produced bars packed against unpacked backgrounds, with no error of any kind. That
suggests more coupling of the same shape may still be undiscovered in a directory this dense.

A half-day spike that gets ONE project's Timeline packing, with interactions already off, will
surface the rest far more cheaply than finding it in Phase 3. Treat the phase estimates as
provisional until that spike lands.
