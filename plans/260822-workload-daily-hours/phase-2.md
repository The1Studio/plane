# Phase 2 — Frontend: daily-hours rename + workday-exact badge capacity

**Plan:** [`plan.md`](plan.md) — read its "The contract (pinned)" section before writing code.
**Depends on:** Phase 1 (the renamed API payload must exist to verify end-to-end).
**Blocks:** Phase 3.
**Effort:** M (~4.5h)

Self-contained: everything needed to start is in this file plus `plan.md`'s contract table.

---

## Goal

Two things, in this order:

1. Rename `max_weekly_hours` → `max_daily_hours` through the type, the read hook, the
   settings page and the toolbar readout — matching Phase 1's wire shape exactly.
2. Replace the timeline badge's capacity source: stop summing `capacity_buckets`, start
   counting the focus range's workdays. This is the behaviour change the user asked for.

---

## File ownership (this phase owns these and nothing else)

```
packages/types/src/workload.ts
packages/workload-ext/src/dateRange.ts
packages/workload-ext/src/i18n.ts
packages/workload-ext/src/WorkloadToolbar.tsx
apps/web/core/hooks/store/use-work-settings.ts
apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx
apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx
apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/page.tsx
```

Do NOT touch `packages/workload-ext/src/merge.ts`, `types.ts`, `heat-color.ts`, or
`WorkloadTimelineChartBlock.tsx`. `capacity_buckets` keeps its meaning and its per-cell
rendering; only the BADGE stops reading it. `total_capacity`/`total_over` are out of scope
per plan D5.

---

## Part A — the rename

### 2.0 — `packages/workload-ext/src/types.ts`

Add the field Phase 1 now emits, next to `buckets` on `TWorkloadRow`:

```ts
/**
 * Hours per CALENDAR month ("2026-08"), independent of the requested
 * granularity. Sparse. Exists because a week bucket is keyed by the date its
 * week begins, so summing week buckets for a month credits a straddling week
 * entirely to the month it started in — see plan D6.
 */
month_buckets?: Record<string, number>;
```

Also extend `merge.ts`'s row merge to carry `month_buckets` through the same spread-merge as
`buckets` (`{ ...base.month_buckets, ...add.month_buckets }`), or a scrolled-in range will
silently drop it. This is the one file the original phase told you not to touch — that
instruction is superseded for this field only; `capacity_buckets`, `total_capacity` and
`total_over` are still out of scope.

### 2.1 — `packages/types/src/workload.ts`

- `max_weekly_hours: number` → `max_daily_hours: number`.
- Update the field's JSDoc: `0 <= x <= 10000 (MAX_HOURS)` still holds; the unit is now
  hours per configured workday.
- Update the type-level docstring line that calls this the weekly cap.

### 2.2 — `apps/web/core/hooks/store/use-work-settings.ts`

- `DEFAULT_WORK_SETTINGS.max_weekly_hours: 40.0` → `max_daily_hours: 8.0`.
- The comment above `DEFAULT_WORK_SETTINGS` promises it mirrors `constants.py`'s `DEFAULT_*`
  verbatim — that promise is what makes this line correct, so keep it and keep the value in
  sync with Phase 1's `DEFAULT_MAX_DAILY_HOURS`.
- Update the module docstring's "(max weekly hours, workdays, first day of week)" list.
- No behavioural change: the hook still sends all three fields on every PUT.

### 2.3 — the workspace settings page

`apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/page.tsx`

- `MAX_WEEKLY_HOURS_CEILING` → `MAX_DAILY_HOURS_CEILING` (value stays `10000`, plan D4).
- The validity check's three `draft.max_weekly_hours` reads → `draft.max_daily_hours`.
- The `onChange` setter key → `max_daily_hours`.
- The `value=` binding → `draft.max_daily_hours`.
- Heading `Max weekly hours` → `Max daily hours`.
- Section description: "Configure the weekly hour cap, workdays, and first day of the week
  used by workload capacity and the calendar across this workspace." → say **daily** hour cap.
- The helper line `Must be a number between 0 and {MAX_DAILY_HOURS_CEILING}.` follows the
  renamed constant.
- Update the file's header comment listing the values it edits.

### 2.4 — toolbar readout + i18n

`packages/workload-ext/src/WorkloadToolbar.tsx`:

- `formatWeeklyHours` → `formatDailyHours` (body unchanged — it only trims a trailing `.0`).
- `formatWorkSettingsReadout` reads `settings.max_daily_hours`.
- Update the example in its docstring to the new string.

`packages/workload-ext/src/i18n.ts`:

- `"toolbar.settings_readout": "Max {hours}h/week · {workdays} · week starts {weekStart}"`
  → `"Max {hours}h/day · {workdays} · week starts {weekStart}"`.
- Placeholder names are unchanged, so no call-site churn beyond 2.4 above.

---

## Part B — the badge

### 2.5 — `countWorkdays` in `packages/workload-ext/src/dateRange.ts`

This is the one new function in the whole plan (see plan.md's prior-art table: zero prior
art across `packages/workload-ext/src/`, `apps/web/core/components/workload/`,
`packages/utils/`).

```ts
/**
 * How many days in the inclusive range [from, to] fall on a configured workday.
 *
 * `workdays` uses Plane's EStartOfTheWeek encoding (SUN=0..SAT=6) — the SAME
 * encoding the API stores and returns, so no remapping happens here. JS's
 * `Date.getUTCDay()` already produces that encoding natively, which is why this
 * needs no counterpart to the backend's `to_plane_weekday()`.
 *
 * Dates are parsed as UTC and stepped by whole UTC days, so a viewer in any
 * timezone counts the same days for the same range.
 */
export function countWorkdays(from: string, to: string, workdays: number[]): number;
```

Requirements:

- Iterate with `Date.UTC` arithmetic (or reuse this file's existing `shiftDate`), never with
  local-time `new Date("YYYY-MM-DD")` day stepping — a DST boundary in a local-time loop
  silently drops or repeats a day, and the badge would be off by one for part of the year.
- Return `0` when `from > to`, mirroring `enumerate_periods`' empty-window behaviour.
- Export it from `packages/workload-ext/src/index.ts` if that file re-exports `dateRange`
  members explicitly (check before assuming a wildcard re-export).

### 2.6 — rewire the badge

`apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx`

- Add a prop carrying the work settings the badge now needs. Pass the whole
  `workSettings: TWorkSettings` rather than two loose numbers — `WorkloadTimelineRoot`
  already holds it (it reads `weekStartDay` from the same source for `focusPeriodFor`), and
  one object keeps the two values that must agree travelling together.
- `periodFigures(row, focus, workSettings)`:
  - **`used` is measured over the same calendar range as `capacity`** (plan D6 — this replaces
    the original "used is unchanged" instruction):
    - **week focus** (day buckets) → sum `row.buckets` entries inside the range, via
      `isInFocus` as today. Day keys cannot straddle, so this is already exact.
    - **month focus** (week buckets) → read `row.month_buckets[focus month]`. Do NOT sum
      `row.buckets`: a week bucket is keyed by the date its week starts, so the `2026-08-31`
      bucket (Aug 31 – Sep 4) would credit four September workdays to August and strip them
      from September. Phase 1 step 1.8 adds `month_buckets` precisely so the client does not
      have to guess at this.
    - **quarter focus** (month buckets) → sum `row.month_buckets` over the quarter's three
      months. Summing `row.buckets` would also be correct here, since a month bucket cannot
      straddle a quarter, but reading one field for both coarse zooms keeps a single code path.
      Derive the focus month key as `focus.from.slice(0, 7)` — `focusPeriodFor` already guarantees
      `focus.from` is the 1st of the month (`monthRange`) or of the quarter's first month
      (`quarterRange`), both verified calendar-exact.
  - `isInFocus` stays as-is and is still used for the week-focus branch. Do not delete it.
  - **`capacity` is now** `countWorkdays(focus.from, focus.to, workSettings.workdays) *
workSettings.max_daily_hours`, rounded via the existing `round2`.
  - **Stop reading `row.capacity_buckets` entirely** in this function.
  - `hasData` no longer means "some bucket fell in focus" — capacity is now always defined
    for a non-null focus. Collapse it: return the `—` placeholder when `focus` is `null`
    (the pre-first-viewport-sync state the current code already handles), and real figures
    otherwise. A member with zero booked hours should read `0h/168h`, not `—`.
  - `over` keeps its definition: `capacity > 0 && used > capacity`.
- **Replace the docstring on `periodFigures`.** The current one explains that summing visible
  buckets guarantees the badge and the heat cells can never disagree. That invariant is
  deliberately gone (plan D3) and the comment must not outlive it. The replacement states:
  capacity is the focus period's own workday count times the daily cap, which is exact at
  every zoom; at month zoom this will NOT equal the sum of the visible week cells
  (5 x 40h = 200h of cells beside a 168h badge for August 2026) because a week bucket carries
  a whole week's capacity even when it straddles the month boundary — the badge answers
  "how much capacity does this month have", the cells answer "how much does this week have".
- Keep the `title={focus?.label}` attribute. It is what tells the reader WHICH period the
  denominator describes, and it matters more now, not less.

### 2.7 — `WorkloadTimelineRoot.tsx`

- Pass `workSettings` down to `WorkloadTimelineSidebarRow` at its existing render site.
  Source it from the same hook call that already supplies `weekStartDay` — do not add a
  second `useWorkSettings()` call, which would double the fetch and could transiently
  disagree with the one driving `focusPeriodFor`.
- No other change: `focusPeriodFor`, the granularity mapping, and the blocks build are
  untouched.

---

## Success criteria

1. `pnpm check` — clean (type-check + lint across the workspace).
2. `grep -rn "max_weekly_hours\|maxWeeklyHours\|MAX_WEEKLY_HOURS\|formatWeeklyHours" apps packages --include=*.ts --include=*.tsx`
   returns **zero**. (`plans/` is excluded — those are frozen records of the prior feature.)
3. Settings page: shows "Max daily hours", loads `8`, saves a changed value, and a reload
   shows the saved value — proving the PUT/GET round-trip matches Phase 1's serializer.
4. Toolbar readout reads `Max 8h/day · Mon, Tue, Wed, Thu, Fri · week starts Monday`.
5. Badge, checked at all three zooms against a workspace on 8h/Mon-Fri:
   - **week zoom** (day buckets, week focus) → denominator `40h`.
   - **month zoom** (week buckets, month focus) → denominator equals that month's workday
     count x 8. August 2026 → **`168h`**, not `200h`. Verify this one specifically, not just
     that the code compiles.
   - **month-boundary correctness** — with an estimate spanning 2026-08-31 to 2026-09-04,
     August's badge must NOT include the Sep 1–4 hours and September's badge MUST include them.
     This is the defect the user asked to have validated; check both months, not just one.
   - **quarter zoom** (month buckets, quarter focus) → sum of the three months' workday
     counts x 8 (Q3 2026: Jul 23 + Aug 21 + Sep 22 = 66 workdays → `528h`).
     Verify the workday counts against a calendar by hand before accepting the rendered number —
     reading them back off the UI proves nothing.
6. A member with zero booked hours in the focused period renders `0h/<capacity>h`, not `—`.
7. Heat cells are visually unchanged from before the change (they still read
   `capacity_buckets`, whose values are identical for the default config per Phase 1).

## Commit

`feat(workload): badge capacity counts the focus period's workdays, not 40h x weeks`
