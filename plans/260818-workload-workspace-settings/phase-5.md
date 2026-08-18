# Phase 5 — Week-start propagation to core UI

**Goal:** make the workspace `week_start_day` the sole source of truth for first-day-of-week
across the whole web app, and remove the per-user preference (D3 — workspace-wide, no override).
Depends on Phases 1 and 4 (`useWorkSettings()` must exist).

Parent plan: [`plan.md`](plan.md).

## Ownership

| File | Change |
|---|---|
| `apps/web/core/components/dropdowns/date.tsx:80` | swap the read |
| `apps/web/core/components/dropdowns/date-range.tsx:113` | swap the read |
| `apps/web/core/components/gantt-chart/chart/root.tsx:95` | swap the read |
| `apps/web/core/components/issues/issue-layouts/calendar/week-days.tsx:81` | swap the read |
| `apps/web/core/components/issues/issue-layouts/calendar/week-header.tsx:24` | swap the read |
| `apps/web/core/store/issue/issue_calendar_view.store.ts:79,137,184,192,205` | store-side read (5 sites) |
| `apps/web/core/components/profile/start-of-week-preference.tsx` | remove the control |
| `apps/web/core/components/power-k/config/preferences-commands.ts:145` | remove the command |

Each is a **core-edit exception** and must be fenced with a
`/* The1Studio fork (workspace work settings) */` comment and registered in the `docs/FORK.md`
table (Phase 6).

## Strategy — one hook, one-line swaps

Every component site is `const startOfWeek = data?.start_of_the_week;` reading the user-profile
store. Replace with `const { week_start_day: startOfWeek } = useWorkSettings();`. That keeps each
core edit to a single line inside a fence, which is what makes the rebase conflict surface
manageable (plan risk table).

**The store file is the exception and the real work.** `issue_calendar_view.store.ts` is a MobX
store, not a component — it cannot call a hook. It reads
`this.rootStore.rootStore.user.userProfile.data?.start_of_the_week` at 5 sites, including a
`reaction()` at line 79 that recomputes the calendar payload when the preference changes.

Approach: add the work-settings observable to the root store (alongside the existing workload
store wiring in `apps/web/ce/store/root.store.ts`, which already hosts workload state) and point
all 5 sites at it, including re-targeting the `reaction()` so the calendar still recomputes when
an admin changes the workspace value.

**Do not** leave the reaction pointed at the old user field — the calendar would then only
recompute on an unrelated profile change, which reads as an intermittent bug rather than a
missing feature.

## Removing the per-user preference (D3)

- `start-of-week-preference.tsx` — delete the component and its usage in the profile
  preferences page. Removing the control is required, not optional: leaving a control that
  silently no longer affects anything is worse than removing it.
- `preferences-commands.ts:145` — remove the power-K command that writes `start_of_the_week`.
- **The `User.start_of_the_week` DB column stays** (D7). It is a core model column and
  `docs/FORK.md` forbids editing `plane/db/migrations/`. It simply becomes unread by the web app.
- `apps/space/store/profile.store.ts:61` — the public space app is **out of scope**; it has no
  workspace-settings access and keeps the per-user default. Note this in `docs/FORK.md` so it is
  not later mistaken for a missed site.

## Tasks

1. Root-store wiring for work settings + the re-targeted `reaction()`.
2. Five component swaps.
3. Five store-site swaps.
4. Preference-control removal (component + power-K command).
5. Grep sweep for stragglers.

## Success criteria

- `pnpm check` clean.
- `grep -rn "start_of_the_week" apps/web packages | grep -v node_modules` returns hits **only** in
  `packages/types/src/users.ts` (the type still mirrors the unread DB column) — zero in
  `apps/web/core`.
- Changing the workspace setting visibly moves the first column in: the calendar layout, the gantt
  week view, both date dropdowns, and the workload matrix — verified manually, not assumed.
- The profile preferences page no longer shows a start-of-week control.
