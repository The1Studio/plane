# Workload timeline — capacity badge, single time control, row structure, clickable work items

Fixes four defects found on `/:workspaceSlug/workload/` (screenshots 2026-08-18), all in the
Phase-8 timeline shipped by [`plans/260818-workload-workspace-settings`](../260818-workload-workspace-settings/plan.md).

| #   | Symptom                                                                                               | Root cause                                                                                                                                                                                                                                      | Phase |
| --- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| 1   | `123h/120h` badge — denominator unrelated to the picked range, moves when _other people's_ tasks move | `periods` is the union of **populated** buckets only (`service.py:438-441`); `capacity_buckets` is keyed off it (`:450-454`) and the sidebar sums that dict (`WorkloadTimelineSidebarRow.tsx:73`)                                               | 1     |
| 2   | Two time-range selectors that do not agree                                                            | Toolbar `Day/Week/Month` sets `store.granularity` (server bucketing); `GanttChartHeader`'s `Week/Month/Quarter` sets `timelineStore.currentView` (pixel zoom). Never wired together — phase-8 task 2 ("zoom wired to granularity") was not done | 2     |
| 3   | Row structure does not match the reference (`image.png`)                                              | Task sidebar cells render `null` (`WorkloadTimelineSidebarRow.tsx:62-70`); no per-person footer; heat cells only exist on populated periods                                                                                                     | 1, 3  |
| 4   | Work item bars are not clickable                                                                      | Task payload carries no `project_id`; `<IssuePeekOverview />` is not mounted on the route                                                                                                                                                       | 4     |

## Target layout

```
┌ sidebar ──────────────────┬ chart (day columns) ───────────────────────┐
│ ⌄ ◯ Trần Thành Công 18.5h/40h │  2h  │ 3.1h │ 3.1h │ 3.1h │ 7.1h │  0h │ ← heat, one cell per period
│   ROLLIC-12  Set up map 3 │  ▬▬▬▬▬▬▬▬ Set up map 3 · 1.5h              │ ← clickable → peek
│   ROLLIC-14  Sniper Canon │            ▬▬▬▬ Sniper Cannon · 4h         │
│   Unscheduled 5   Overdue 2                                            │ ← footer block
├───────────────────────────┼────────────────────────────────────────────┤
│ ⌄ ◯ Phạm Văn Sơn  26.7h/40h │ 3.3h │ 5.3h │  9h  │  9h  │  0h  │  0h  │
└───────────────────────────┴────────────────────────────────────────────┘
```

## Decisions

- **D1 — the badge is per-week.** `NNh/40h` for one focused week, matching the reference, **not**
  a window total. Delivered as a new granularity-independent `weekly_buckets` map on each row so
  the badge works identically at day / week / month bucketing. The focused week is the week
  containing the workspace's today, clamped into `[date_from, date_to]`.
- **D2 — `periods` spans the requested window.** Independent of D1 and required on its own: it is
  what puts a heat cell (including `0h`) on every visible column, and what makes `capacity_buckets`
  / `total_over` mean something. Union of the window's periods with the populated ones, so a task
  clipped in from outside the window is never dropped.
- **D3 — one time control, zero core edits.** The toolbar's `Day/Week/Month` tabs are deleted;
  `GanttChartHeader`'s existing `Week/Month/Quarter` becomes the single control and drives
  `store.granularity` (`week→day`, `month→week`, `quarter→month`). Rejected alternative: threading a
  `hideViewSwitcher` prop through `GanttChartRoot → ChartViewRoot → GanttChartHeader` — three core
  files, a `docs/FORK.md` exception, and three rebase conflict points, to move a control we can
  simply adopt.
- **D4 — full-match layout at a uniform row height.** The reference's per-person footer becomes a
  third block kind rather than a taller header row, so every row stays at core's shared
  `BLOCK_HEIGHT` (44px, hardcoded in `blocks/block-row.tsx`) and **no core edit is needed**.
- **D5 — click opens the peek overlay**, `ControlLink`-wrapped so cmd/ctrl/middle-click still opens
  the full work-item page. Same affordance as core's own gantt layout
  (`issues/issue-layouts/gantt/blocks.tsx:129-150`).
- **D6 — over-capacity means over _for a week_.** The header tint and the "Over capacity only"
  filter switch from `total_over` (window total) to "any week in `weekly_buckets` exceeds
  `max_weekly_hours`". `total_over` stays in the payload — it is now correct under D2 — but stops
  being the headline signal.

## Isolation (docs/FORK.md)

Backend changes are confined to the existing fork app `apps/api/plane/workload/`. Frontend changes
are confined to `packages/workload-ext/src/`, `apps/web/core/components/workload/timeline/`, and the
fork-owned route page. **No core file is edited** — see D3 and D4 for the two places that was
considered and avoided. Touch-points 1–7 are untouched; no new migration.

## Propagation (CLAUDE.md standing rule)

Phase 1 changes the `GET /api/workload/workspaces/<slug>/` response shape (`periods`,
`weekly_buckets`, `weekly_capacity`, `tasks[].project_id`). That must reach `plane-mcp-server`'s
`get_workload` tool and the two SDKs — Phase 6.

## Phases

| Phase           | Title                                                       | Depends on |
| --------------- | ----------------------------------------------------------- | ---------- |
| [1](phase-1.md) | API — window-complete periods, weekly buckets, `project_id` | —          |
| [2](phase-2.md) | Single time control                                         | 1          |
| [3](phase-3.md) | Row structure — task labels, footer block, weekly badge     | 1          |
| [4](phase-4.md) | Clickable work items — peek overlay                         | 1, 3       |
| [5](phase-5.md) | i18n, verification, fork docs                               | 2, 3, 4    |
| [6](phase-6.md) | Downstream propagation (MCP + SDKs)                         | 1          |

Phases 2, 3 and 4 touch disjoint files after Phase 1 lands and can run in parallel; 4 needs 3's
sidebar task row to exist as its click target.

## Success criteria

- The badge reads `41h/40h` (weekly), not `123h/120h`, and does not change when an unrelated
  member's task moves.
- Exactly one time-range control is visible; changing it re-buckets the data AND re-zooms the axis.
- Every visible column has a heat cell, including `0h` columns.
- Task rows carry an identifier + name in the sidebar; clicking either the label or the bar opens
  the peek panel; cmd-click opens the full page.
- Each swimlane ends with an Unscheduled / Overdue footer.
- `pnpm check` clean · `pytest apps/api/plane/workload/tests` green ·
  `python manage.py makemigrations --check --dry-run` clean.
