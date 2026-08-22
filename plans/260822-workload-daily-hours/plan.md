# Workload: daily hour cap + workday-exact badge capacity

**Created:** 2026-08-22
**Repo:** The1Studio/plane (`company-main`)
**Owning fork app:** `apps/api/plane/workload/` + `packages/workload-ext/` + `apps/web/core/components/workload/`

---

## Goal

Two changes to the workload feature, both about how capacity is expressed and totalled:

1. **Configure the hour cap per DAY, not per week.** `WorkloadSettings.max_weekly_hours`
   (default `40.0`) becomes `max_daily_hours` (default `8.0`), everywhere — DB column,
   both APIs, the TypeScript type, and the workspace settings UI.
2. **Make the timeline badge's capacity workday-exact.** At month zoom the badge currently
   sums WEEK buckets, so a month reads `40h x week-count` (160h or 200h) instead of that
   month's real workday count. The badge's capacity becomes
   `workdays(focus.from .. focus.to) x max_daily_hours`, computed from the focus range —
   correct for the week, month and quarter focus alike.

---

## Prior art — what already exists

Searched `apps/api/plane/workload/`, `packages/workload-ext/`, `packages/types/`,
`apps/web/core/components/workload/`, `apps/web/core/hooks/store/`, and the four prior
workload plans under `plans/`.

| Concern | Already exists | Where |
|---|---|---|
| Workspace-wide work settings model | YES — `WorkloadSettings` (max_weekly_hours, workdays, week_start_day) | `workload/models.py` |
| Pure capacity proration, per granularity | YES — `capacity_for_period()`, stdlib-only, unit-tested with no DB | `workload/aggregation.py` |
| Workday predicate + month workday count | YES — `_is_workday()`, `_workdays_in_month()` | `workload/aggregation.py` |
| Plane weekday encoding (SUN=0..SAT=6) + converter | YES — `to_plane_weekday()`, the single place the two conventions meet | `workload/constants.py` |
| Settings defaults consumed on a GET with no row | YES — `settings_get()` returns constants, never writes on read | `workload/views.py` |
| Client-side work-settings read path | YES — `useWorkSettings()`, single place that knows the API shape | `apps/web/core/hooks/store/use-work-settings.ts` |
| Badge focus period (week / month / quarter from chart centre) | YES — `focusPeriodFor()`, already returns an exact `{from, to}` range | `.../workload/timeline/blocks.ts` |
| Client-side date/period math | YES — `periodDateRange()`, `shiftDate()` | `packages/workload-ext/src/dateRange.ts` |
| A workday COUNTER over an arbitrary date range (client-side) | **NO — zero across `packages/workload-ext/src/`, `apps/web/core/components/workload/`, `packages/utils/`.** This is the one genuinely new function. | to be added in `dateRange.ts` |
| An MCP tool wrapping `/work-settings/` | **NO — zero across `~/Projects/plane-mcp-server/src/`** (checked the local clone; no `work-settings`, no `max_weekly_hours`). The rename cannot break an MCP tool that does not exist. | n/a |

Consequence: this is a rename plus one arithmetic change plus one new 15-line helper.
No new model, no new endpoint, no new component. Every seam it needs is already cut.

---

## Decisions (resolved with the user, 2026-08-22 — not open)

| # | Decision |
|---|---|
| D1 | **Existing rows reset to the new `8.0` default.** The migration drops `max_weekly_hours` and adds `max_daily_hours` with `default=8.0`; it does NOT divide the old value by the workday count. A workspace that had customised its weekly cap re-enters it once, in the new unit. |
| D2 | **Rename everywhere, no backward-compat alias.** DB column, app API, public `/api/v1/` API, `TWorkSettings`, settings UI. The public-API shape changes in one step; no serializer branch accepts the old key. |
| D3 | **Badge capacity is computed client-side from the focus range**, not summed from `capacity_buckets`. `capacity = countWorkdays(focus.from, focus.to, workdays) * max_daily_hours`. Heat cells keep showing per-bucket capacity, so at month zoom the badge (e.g. `168h`) deliberately will NOT equal the sum of the visible week cells (`5 x 40h`). That divergence is the point of the change and is documented at the call site. |
| D4 | `MAX_HOURS = 10000` stays as the shared upper bound for both the per-issue estimate and the daily cap. It is a safety bound against absurd input, not a business rule, and keeping one constant keeps the serializer/model/aggregation SSOT intact. |
| D5 | `total_capacity` / `total_over` in the API response keep their current bucket-sum definition and therefore keep the same `40h x weeks` skew at week granularity. **Known non-conformant, deliberately out of scope:** both are computed but rendered NOWHERE (`grep total_capacity apps/web packages` → only `merge.ts` and `types.ts`). Fixing an unrendered field would be scope creep; this row exists so the next reader does not mistake it for an oversight. |

---

## Fork-discipline compliance

Every file this plan touches is fork-owned. **Zero core edits, zero new touch-points.**

- Backend changes are confined to `apps/api/plane/workload/` — a fork-owned Django app with
  its own `migrations/`, per `docs/FORK.md`.
- No column is added to any core model; `WorkloadSettings` is a fork table.
- Frontend changes are confined to `packages/workload-ext/`, `packages/types/src/workload.ts`
  (fork-owned file), `apps/web/core/hooks/store/use-work-settings.ts` (fork-owned file),
  `apps/web/core/components/workload/` (fork-owned directory), and the fork-owned settings
  page under `apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/`.
- `apps/web/app/routes/extended.ts` is NOT touched — no new route.

---

## Phases

| Phase | File | Owns | Effort |
|---|---|---|---|
| 1 | [`phase-1.md`](phase-1.md) | Backend: constants, model + migration, aggregation math, serializer/views/service, backend tests | M (~5.5h) |
| 2 | [`phase-2.md`](phase-2.md) | Frontend: `TWorkSettings`, work-settings hook, settings page, toolbar readout + i18n, `countWorkdays`, badge rewiring | M (~4.5h) |
| 3 | [`phase-3.md`](phase-3.md) | Downstream propagation issues in the sibling repos (standing rule) | S (~1h) |

**Phases 1 and 2 are sequential, not parallel.** Phase 2's settings page and toolbar assert
against the renamed API payload, so Phase 1's serializer must land first for Phase 2 to be
verifiable end-to-end. Phase 3 runs only after both are green.

### File ownership — zero overlap

No file appears under two phases.

| Phase | Files |
|---|---|
| 1 | `apps/api/plane/workload/constants.py`, `models.py`, `migrations/0006_*.py`, `aggregation.py`, `serializers.py`, `views.py`, `service.py`, `tests/test_work_settings.py`, `tests/test_workload_db.py`, `tests/test_aggregation_pure.py` |
| 2 | `packages/types/src/workload.ts`, `packages/workload-ext/src/dateRange.ts`, `packages/workload-ext/src/i18n.ts`, `packages/workload-ext/src/WorkloadToolbar.tsx`, `apps/web/core/hooks/store/use-work-settings.ts`, `apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx`, `apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx`, `apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/page.tsx` |
| 3 | none in this repo — issues only, filed in sibling repos |

---

## The contract (pinned — both phases code against this verbatim)

Renamed wire field on `GET`/`PUT` `/api/workspaces/<slug>/work-settings/` **and**
`/api/v1/workspaces/<slug>/work-settings/`:

```jsonc
{
  "max_daily_hours": 8.0,        // float, 0 <= x <= 10000 (MAX_HOURS). WAS: max_weekly_hours (40.0)
  "workdays": [1, 2, 3, 4, 5],   // unchanged — EStartOfTheWeek, SUN=0..SAT=6
  "week_start_day": 1            // unchanged
}
```

`capacity_for_period(max_daily_hours, period, granularity, workdays)` — new definitions:

| granularity | before (weekly basis) | after (daily basis) |
|---|---|---|
| `day` | `max_weekly_hours / len(workdays)` on a workday, else `0.0` | `max_daily_hours` on a workday, else `0.0` |
| `week` | `max_weekly_hours` | `max_daily_hours * len(workdays)` |
| `month` | `max_weekly_hours * (workdays_in_month / len(workdays))` | `max_daily_hours * workdays_in_month` |

**These are algebraically identical** when `max_daily_hours == max_weekly_hours / len(workdays)`.
For the default config (40/5 = 8, Mon-Fri) every server-side capacity number, heat cell and
`over` flag is byte-identical before and after. That is the regression bar for Phase 1: the
rename must change no output for a default workspace.

Badge capacity (Phase 2, client-side — this is the only number that intentionally changes):

```
capacity = countWorkdays(focus.from, focus.to, workSettings.workdays) * workSettings.max_daily_hours
used     = sum of row.buckets whose period key starts inside [focus.from, focus.to]   // unchanged
```

---

## Risk Assessment

| Risk | Likelihood (1-5) | Impact (1-5) | Score | Mitigation |
|---|---|---|---|---|
| A `max_weekly_hours` reference is missed and the settings PUT 400s in production | 2 | 4 | 8 | Phase 2 ends with a repo-wide `grep -rn "max_weekly_hours\|maxWeeklyHours\|MAX_WEEKLY_HOURS"` excluding `plans/` and `node_modules/`, asserted to return zero. The historical `plans/` hits are frozen records of a past feature and are deliberately left untouched. |
| D1's reset silently lowers/raises a real workspace's capacity | 3 | 3 | 9 | Accepted by the user as D1. Phase 1 records the pre-migration values in the migration's docstring path (`SELECT workspace_id, max_weekly_hours FROM workload_settings`) so an admin can re-enter them; the fields are re-editable in the settings UI. |
| The badge/heat-cell divergence at month zoom reads as a bug to users | 3 | 2 | 6 | The badge already carries a `title` naming its focus period. Phase 2 keeps that and adds the divergence rationale as a code comment at `periodFigures`. |
| Migration ordering: `0006` collides with a concurrently authored migration | 1 | 3 | 3 | `makemigrations --check --dry-run` is already a CI gate (`company-main-ci.yml`); a collision fails the build rather than shipping. |
| `capacity_for_period`'s `len(workdays)` divide is removed from the `day` branch, hiding the empty-workdays guard | 2 | 3 | 6 | The `week` branch still multiplies by `len(workdays)`, and the model's `ck_workload_settings_workdays_nonempty` CheckConstraint plus the serializer guard are both unchanged. Phase 1 keeps the existing empty-workdays test. |
| Sibling SDKs keep binding the old field name | 3 | 2 | 6 | Phase 3 files issues per the propagation matrix. Confirmed already: no MCP tool wraps this endpoint, so the MCP surface is unaffected. |

Highest score is 9 — no risk at or above 15, no phase is gated on further mitigation.

## Timeline

| Phase | Effort | Notes |
|---|---|---|
| Phase 1: Backend daily hours | M (~5.5h) | Blocks Phase 2's end-to-end verification |
| Phase 2: Frontend rename + badge capacity | M (~4.5h) | Depends on Phase 1 |
| Phase 3: Downstream propagation | S (~1h) | Depends on 1 + 2 green |
| **Total** | **~11h** | Critical path: Phase 1 → Phase 2 → Phase 3 (fully sequential) |

---

## Definition of done

- `grep -rn "max_weekly_hours" apps packages --include=*.py --include=*.ts --include=*.tsx` returns zero.
- `python manage.py makemigrations --check --dry-run` clean; `python manage.py check` clean.
- Backend workload test suite green, including a new test asserting `capacity_for_period`
  output is unchanged for the default 8h/Mon-Fri config vs. the old 40h/week config.
- `pnpm check` clean.
- The workspace settings page reads "Max daily hours" and round-trips `8` through PUT/GET.
- At month zoom, an assignee's badge denominator equals that month's workday count x 8
  (e.g. August 2026 → `168h`, not `200h`).
- Propagation issues opened in the sibling repos, URLs reported.
- `CLAUDE.md` "Custom features" workload entry updated to describe the daily cap and the
  focus-range badge.
