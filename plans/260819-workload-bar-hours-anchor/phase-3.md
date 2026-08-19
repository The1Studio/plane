# Phase 3 — Week bucket end dates were a day early west of Greenwich

**Plan:** [plan.md](plan.md)
**Effort:** S (<0.5h)
**Added:** mid-cook, from a finding surfaced while reading Phase 2's date math
**Depends on:** nothing (independent of Phases 1 and 2)

## Symptom

For any user at a negative UTC offset, every week-granularity capacity heat cell in
the workload timeline header ends — and therefore is positioned — one day early.
Silent: nothing errors, the cells simply sit one column off.

## Root cause

`packages/workload-ext/src/dateRange.ts` → `shiftDate`:

```ts
const d = new Date(dateStr); // "2026-08-17" → parsed as UTC midnight
d.setDate(d.getDate() + days); // getDate() reads the LOCAL calendar
```

A bare `YYYY-MM-DD` is parsed by `Date` as **UTC** midnight, while `getFullYear`,
`getMonth`, and `getDate` read the **local** calendar. At a negative offset, UTC
midnight is already the previous day locally, so the local date is one behind before
a single day is added — and the formatted result comes back 24h early.

Measured, `shiftDate("2026-08-17", 6)`:

| TZ                     | before         | after      |
| ---------------------- | -------------- | ---------- |
| UTC                    | 2026-08-23     | 2026-08-23 |
| Asia/Ho_Chi_Minh (+07) | 2026-08-23     | 2026-08-23 |
| America/New_York       | **2026-08-22** | 2026-08-23 |
| America/Los_Angeles    | **2026-08-22** | 2026-08-23 |
| Pacific/Honolulu       | **2026-08-22** | 2026-08-23 |

`periodDateRange(period, "week")` derives a week bucket's END from this
(`shiftDate(period, 6)`), and `WorkloadTimelineChartBlock`'s header branch positions
each heat cell from that `{ start, end }` range — so the whole row shifts.

This is why the bug went unnoticed locally: the development timezone is +07:00, where
UTC midnight is 07:00 the same local day and the two calendars agree.

## Change

`packages/workload-ext/src/dateRange.ts`:

```ts
const d = new Date(`${dateStr}T00:00:00`); // parses as LOCAL
```

`T00:00:00` makes the string parse in the same calendar the getters read. This is the
idiom `periodKeyFor` in `./merge.ts` already uses — the fix aligns the two rather than
inventing an approach.

`daysBetween` is **deliberately left on its bare (UTC) parse.** It only subtracts two
identically-offset instants, so the result is an exact multiple of 86_400_000 and no
local calendar is consulted. Converting it for symmetry would reintroduce DST, where a
spring-forward day is 23h. A docblock now says so, so a future reader tidying for
consistency does not "fix" it into a bug.

## Success criteria

1. `shiftDate("2026-08-17", 6)` returns `2026-08-23` under UTC, Asia/Ho_Chi_Minh,
   America/New_York, America/Los_Angeles and Pacific/Honolulu. **Verified** by direct
   multi-timezone execution.
2. DST is unaffected in both directions: `shiftDate("2026-03-07", 6)` → `2026-03-13`
   and `shiftDate("2026-10-31", 6)` → `2026-11-06`, with `daysBetween` reporting 6 for
   both, under America/New_York, Europe/Berlin and Asia/Ho_Chi_Minh. **Verified.**
3. `@plane/workload-ext` typechecks, lints clean, and builds.
4. The web app typechecks against the rebuilt package.

## Note on `dist/`

`packages/workload-ext` is consumed through `./dist/index.mjs`, but `dist/` is
gitignored and built by turbo — nothing to commit. The local rebuild
(`pnpm --filter @plane/workload-ext build`) was only to confirm the emitted bundle
carries the change and that the web app still typechecks against it.
