# Phase 5 — Verification, FORK.md, propagation

**Goal:** prove it, and record the divergence honestly. Depends on 2, 3, 4. Parent: [`plan.md`](plan.md).

## 5.1 — Gates

```bash
pnpm --filter web check:types
pnpm --filter web check:format
pnpm --filter web check:lint          # 0 errors repo-wide
npx oxlint <paths you touched>        # must be 0 WARNINGS too — the pre-commit hook denies them

pnpm --filter @plane/workload-ext build   # verify-merge runs against dist/, so build first
node packages/workload-ext/verify-merge.mjs

# Backend is untouched by this plan; run it only as a collateral-damage check.
# Needs Python 3.12 + Postgres with pgvector on template1 + live Redis — see
# plan.md "Working context" before assuming a red result is your fault.
DJANGO_SETTINGS_MODULE=plane.settings.test pytest plane/workload
```

A rebuild of `@plane/workload-ext` is required before the verifier, and is easy to forget: it
imports from `dist/`, so without it you are testing the PREVIOUS build and every check passes
whatever you just changed. That is a green that proves nothing.

## 5.2 — What the gates cannot tell you

None of the above renders a pixel. Every claim this plan makes about layout is unverified until a
human opens a browser. The checks a person must run, on a project with enough items to matter:

1. A Timeline with 200 work items is a handful of rows tall, not 200.
2. Two items that overlap in time are never drawn on the same row.
3. Two items that touch (one ends the day the next starts) are on separate rows, not fused.
4. Bar labels sit flush left with no 360px gap where the sidebar used to be.
5. Clicking a bar still opens the peek panel; cmd-click still opens the full page.
6. Scrolling right pages in more items, once, not once per frame.
7. The workload board still aligns: header, lanes and footer line up per member.
8. Workload's capacity badge still tracks the viewport centre.

State which of these were actually performed. "Should work" is not one of them.

## 5.3 — FORK.md

This earns the fork's largest core-edit exception. Record, in `docs/FORK.md`:

- The files rewritten under `gantt-chart/` and that the divergence is **semantic**, not textual —
  an upstream change to how blocks render will not merge cleanly into a lane model, and the
  resolution is to re-apply the lane model rather than to take either side.
- That interactions are disabled, with a pointer to [`later.md`](later.md), so a future reader
  does not conclude the drag code is dead and delete it.
- That the sidebar removal is unconditional and the slot is content-driven, so nobody adds a
  `showSidebar` flag back.

## 5.4 — Propagation

No API change, so no SDK or MCP work. `CLAUDE.md`'s standing rule is satisfied by the FORK.md
entry alone — say so explicitly in the PR rather than leaving it ambiguous.
