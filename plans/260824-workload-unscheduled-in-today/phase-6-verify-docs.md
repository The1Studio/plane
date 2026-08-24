# Phase 6 — verify, document, and close the D8 contradiction

**Owns:** `packages/workload-ext/verify-merge.mjs`, `CLAUDE.md`, `docs/FORK.md`,
`plans/260824-workload-timeline-scheduling/plan.md`
**Estimate:** 2h
**Depends on:** phase 5 (and phase 2, for the backend half)

## Verification

```bash
# backend (phase 1)
cd apps/api && python manage.py check && pytest plane/workload/tests/ -q
python manage.py makemigrations --check --dry-run   # must report NO changes

# frontend (phases 2-5)
node packages/workload-ext/verify-merge.mjs
pnpm --filter web typecheck
pnpm --filter @plane/workload-ext build
pnpm --filter web build
```

`makemigrations --check` is owed here and was not in the original frontend-only shape of this plan.
Phase 1 adds no model and no field, so it must report no changes — if it reports any, something was
added to a model that this plan says it did not touch.

Run the fork's isolation audit (`plane-isolation-audit`) and confirm the diff touches only the files
in plan.md's ownership table. A hit under `apps/web/core/components/gantt-chart/`, or a new
migration under `plane/db/migrations/`, means a decision was worked around.

## Rewrite D8 in the other plan

`plans/260824-workload-timeline-scheduling/plan.md` currently reads:

> D8 — A task with no `target_date` is never drawn and is therefore never draggable.

That is now false, and leaving it is worse than a stale note: it is a decision table a future reader
will treat as current and design against. Rewrite the second half in place, keeping the first:

> D8 — A task with no `start_date` (bar drawn from `target_date` alone) gets both dates written on a
> move, and gains a `start_date` on a left-resize. A task with no `target_date` was originally not
> drawn at all; it is now drawn as a dashed placeholder at `start_date ?? today` and is draggable —
> see `plans/260824-workload-unscheduled-in-today/`, which supersedes this half of D8.

Do not delete the original wording. A superseded decision that says what it used to say, and why it
changed, is worth more than one that reads as if it had always been this way.

## Documentation

**`CLAUDE.md`**, in the `workload/` bullet under "Custom features (fork-owned)". Extend the existing
paragraph — the entry is deliberately one paragraph per app, not a bullet list. The facts a future
reader cannot recover from the code:

*Members with no work (phases 1–2)*

- Every active, non-bot `ProjectMember` of the in-scope projects gets a row, whether or not they
  carry estimated work. This is **unconditional** — there is no `include_empty_members` parameter —
  so **`rows.length` counts PEOPLE, not work**, and any consumer reading row count as "is there work
  here" is wrong. Rows for a member with zero assigned items and for one whose items are all
  unestimated are indistinguishable, on purpose.
- An empty row carries `total: 0`, `tasks: []`, and a **fully populated `capacity_buckets`** — the
  unused capacity is the point of the row.
- Membership deliberately mirrors `_resolve_owners`: active `ProjectMember`, non-bot, not
  soft-deleted. Not `WorkspaceMember` — a member with no in-scope project would get a lane nothing
  could fill. The assignee filter narrows empty rows too, so filtering to one member shows one lane.
- Ordering is unchanged: `Unassigned` pinned first, then alphabetical, empty and loaded interleaved.

*Unscheduled work (phases 3–5)*

- Unscheduled work items (`target_date === null`) are drawn as dashed placeholder bars at
  `start_date ?? today`, one per row, capped at three per swimlane (`MAX_UNSCHEDULED_LANES`); the
  footer strip reports **only the overflow** (`Unscheduled (27 more)`), never the total, so the count
  and the visible bars must not be added together.
- Those bars' hours are in **no** capacity cell — the API routes an unscheduled estimate to its
  separate `unscheduled` bucket, never to `buckets`, so a bar reading `4h` sits above a heat cell
  that excludes it. Deliberate, not a rounding gap.
- The server-side 200-task cap sorts null dates **last**, so a member with more than 200 estimated
  items loses their unscheduled tasks from the payload before the client can draw any.
- Dropping such a bar on a date writes both `start_date` and `target_date`, and the bar becomes a
  normal solid one.

**`docs/FORK.md`** — no new core-edit exception is created; every file is fork-owned and `workload/`
is an existing app with no new touch-point entry. State that in the report. Touch `FORK.md` only if
the isolation audit disagrees, in which case the finding is the news, not the doc edit.

## Propagation — required, and this reverses an earlier conclusion

An earlier revision of this plan concluded **no propagation**, on the grounds that the work added no
endpoint and no response field. That was correct while the plan was frontend-only. **D12 makes it
wrong**: `get_workload` now returns rows it never returned before, for every caller, with no flag to
opt out. A behaviour change to an existing endpoint propagates the same as a shape change — the
sibling matrix keys on what a consumer sees, not on whether a field was added.

Per `.claude/skills/plane-propagate/references/sibling-repos.md`, open a tracking issue or PR in
each — **never edit a sibling repo from this repo's PR**:

| Repo | What it needs |
| --- | --- |
| `plane-mcp-server` | `get_workload`'s docstring must state that rows include members with no work, that `rows.length` therefore counts people rather than work, and that an empty row carries a full `capacity_buckets`. An MCP caller inferring "no work in this workspace" from row count will make this repo's own phase-2 mistake with nothing to warn them. |
| `plane-node-sdk`, `plane-python-sdk` | Response-shape documentation for the same behaviour change, if either documents the workload row set. |
| `docs` / `developer-docs` | Only if the workload endpoint's response is described there. |

The unscheduled half (phases 3–5) still propagates **nothing** on its own — it adds no endpoint, no
parameter, and no field, and `tasks[]` already carried null-target tasks. Record both conclusions
with their reasoning in the PR description. A no-propagation call that says why is a finished check;
silence is indistinguishable from a forgotten one.

## PR

Conventional-commit scope `workload`, matching the sibling commits (`feat(workload): ...`). Reference
this plan directory and the PLANE work items. If phases 1–2 shipped on their own branch ahead of the
rest (see plan.md § Status), they carry their own PR and their own propagation issues, and this one
covers only phases 3–6.

Then babysit to green and admin-merge per the repo's standing practice, remembering that a merge to
`company-main` triggers the self-hosted deploy.
