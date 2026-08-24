# Phase 3 — documentation and end-to-end verification

**Owns:** `CLAUDE.md`, `docs/FORK.md`
**Estimate:** 1h
**Depends on:** phase 2 (the docs describe what it renders; the visual check needs it running)

## Goal

Bring the two fork-SSOT documents into step with what the timeline now draws, and confirm by
looking at the running app rather than by reasoning about the diff.

## `CLAUDE.md` — "Custom features (fork-owned)" → `workload/`

That entry already documents the bar's rendering contract at this granularity (it records that lane
rows carry no sidebar label, that the blank cell is a deliberate `BLOCK_HEIGHT` spacer, and how the
capacity badge is measured). Add, in the same register:

- Task bars render at three densities. **Week** shows the work-item identifier in a small dimmed
  line above the name and hours, in a 40px bar; **Month and Quarter** show the estimate alone,
  centred, with the name available only from the hover tooltip.
- A bar never renders a partial number: the estimate steps down from `text-11` to `text-9` and then
  disappears entirely rather than clipping.
- The minimum bar width is 30px — one day at Quarter zoom, the only zoom where the floor binds.
  It was 60px, and the change is visible: **a 1-day task at Quarter zoom is now drawn half as
  wide as before.** Worth stating outright, because it looks like a regression to anyone who
  remembers the old width.

Keep it to the existing terse style — this is an operator note, not a design doc.

## `docs/FORK.md`

Two places to touch, both in the workload timeline section (around the existing `dayWidth`
discussion near line 617 and the badge discussion near line 675):

1. Record that `MIN_BAR_WIDTH` moved 60 → 30 and, more importantly, that its **meaning** changed
   from a label floor to a duration floor. The label guarantee now lives in
   `packages/workload-ext/src/barLabel.ts`. Anyone reading the `dayWidth` table needs the pointer,
   because those two constants are now coupled: change a `dayWidth` and the fit tests are what
   tells you whether labels still render.
2. Add `barLabel.ts` to whatever inventory of `packages/workload-ext` modules that section keeps,
   with a one-line purpose.

**No new core-edit exception row.** This change touches no core file — check that claim before
writing it: `git diff --name-only company-main...HEAD` should list only
`packages/workload-ext/**`, `apps/web/core/components/workload/**`, the two docs, and this plan
directory. Anything else appearing there means a customization leaked into core and the isolation
convention was broken (`.claude/rules/plane-fork-discipline.md`).

## Propagation check — expected to be a no-op

Run the classification honestly rather than assuming: this change adds no endpoint, no request
parameter, and no response field. `TWorkloadTask.identifier` was already in the payload and already
rendered in the tooltip. So nothing propagates to `plane-mcp-server`, `plane-node-sdk`,
`plane-python-sdk`, or `plane-claude-plugin`.

State that conclusion in the PR description with the reason, so a reviewer can check the reasoning
instead of taking "no propagation needed" on trust.

## Verification

```
pnpm --filter @plane/workload-ext test
pnpm check
```

Then, in the running app on `/:workspaceSlug/workload`, walk all three zooms and confirm each
success criterion from `plan.md` by eye. Capture a screenshot per zoom for the PR — the whole change
is visual, so a diff review cannot substitute for one.

Specifically look for the two things a green build cannot tell you:

- A Quarter-zoom bar whose estimate has two decimals. It must read whole or read nothing. If it
  reads `0.75`, phase 1's character-width estimate is under-predicting and its constants need
  raising, not the floor.
- A Week-zoom bar sitting directly above another lane row. The 40px bar must not visually collide
  with the row beneath it.
