# Phase 5 — i18n, verification, fork docs

**Goal:** no untranslated string, no unverified claim, and the fork's own docs telling the truth
about what changed. Depends on Phases 2, 3, 4. Parent: [`plan.md`](plan.md).

## Ownership

- `packages/workload-ext/src/i18n.ts`
- `docs/FORK.md`, `CLAUDE.md`
- test files only, across both stacks

## 5.1 — i18n

New keys, all through the package's existing `wlt()`:

| Key                           | English                                               |
| ----------------------------- | ----------------------------------------------------- |
| `timeline.week_of`            | `Week of {date}` (badge tooltip)                      |
| `timeline.footer_unscheduled` | `Unscheduled ({count})`                               |
| `timeline.footer_overdue`     | `Overdue ({count})`                                   |
| `toolbar.range_clamped`       | `Range shortened to {days} days for this zoom level.` |

Removed with the tabs: `granularity.day` / `granularity.week` / `granularity.month` and
`filters.granularity` — delete them rather than leaving orphans, and grep to confirm no other
caller.

## 5.2 — Verification gates

```bash
pnpm check                                              # types + lint, whole workspace
pytest apps/api/plane/workload/tests                    # fork app suite
python manage.py makemigrations --check --dry-run       # no stray model change
python manage.py check
```

Manual, against the reference screenshot — each of these is a claim this plan makes and none is
provable from a type-check:

1. Badge reads `NNh/40h` and does not move when a _different_ member's task is rescheduled.
2. One `Week/Month/Quarter` control on the page; changing it re-buckets and re-zooms together.
3. `quarter -> week` on a long range yields a 200, not a 400.
4. Every visible column has a heat cell, `0h` included.
5. Click a bar -> peek opens; cmd-click -> new tab; edit a date, close, board updates.
6. Collapse a member -> tasks and footer hide, header stays, other rows stay aligned.

## 5.3 — Fork docs

- `CLAUDE.md` "Custom features" — extend the `workload/` line with the weekly-capacity badge and
  peek integration.
- `docs/FORK.md` — no new touch-point and no new core-edit exception. Record that explicitly: this
  change set deliberately avoided two candidate core edits (`GanttChartHeader`'s view switcher,
  `BLOCK_HEIGHT`), and the next person to want a taller header row should know it was considered.
- Confirm `workload` is present in the `forkApps` registry that `company-main-ci.yml` reads — the
  new backend tests are only run if it is.

## Success criteria

- All four gates above green, output pasted into the PR body, not summarised.
- Six manual checks confirmed in a browser, not asserted.
- `grep -rn "granularity\." packages/workload-ext apps/web/core/components/workload` returns no
  orphaned i18n key.
