# Phase 0 — Shared contract (serial gate)

**Goal:** pin every shape that more than one later phase depends on, so Phases 1 and 2 can run
concurrently without inventing divergent conventions. Nothing else starts until this lands.

Parent plan: [`plan.md`](plan.md).

## Ownership

- `apps/api/plane/workload/constants.py` (new)
- `packages/types/src/workload.ts` (new) + its export line in `packages/types/src/index.ts`

## The contract

### Weekday encoding (D6)

One convention crosses the API: **Plane's `EStartOfTheWeek`** — `SUNDAY=0, MONDAY=1, … SATURDAY=6`
(`packages/types/src/users.ts:15-23`). Python's `date.weekday()` is Mon=0..Sun=6 and is converted
**only** inside `aggregation.py`:

```python
# apps/api/plane/workload/constants.py
def to_plane_weekday(d: date) -> int:
    """date.weekday() (Mon=0..Sun=6) -> Plane encoding (Sun=0..Sat=6)."""
    return (d.weekday() + 1) % 7
```

### Defaults

```python
DEFAULT_MAX_WEEKLY_HOURS = 40.0
DEFAULT_WORKDAYS = [1, 2, 3, 4, 5]   # Mon-Fri in Plane encoding
DEFAULT_WEEK_START_DAY = 1           # Monday — preserves today's ISO-week bucketing
```

`DEFAULT_WEEK_START_DAY` is **Monday** (confirmed decision), not Sunday: today's buckets are ISO weeks
(`aggregation.py:56-58`), so Monday is the value that leaves existing workspaces' week columns
unchanged. This deliberately differs from core's per-user default (Sunday, `user.py:252`).

### API payload

`GET|PUT /api/workspaces/<slug>/work-settings/` and
`GET|PUT /api/v1/workspaces/<slug>/work-settings/`:

```jsonc
{
  "max_weekly_hours": 40.0, // float, 0 <= x <= MAX_HOURS (10000)
  "workdays": [1, 2, 3, 4, 5], // int[], non-empty, unique, each 0..6, ascending
  "week_start_day": 1, // int, 0..6
}
```

GET is `ADMIN|MEMBER` (workspace level, so non-admins can render correct week columns and the
read-only cap badge). PUT is `ADMIN` only. Mirrors the existing split at
`apps/api/plane/workload/views.py:361-371`.

A workspace with no row returns the defaults above rather than 404 — callers never branch on absence.

### TypeScript mirror

```ts
// packages/types/src/workload.ts
export type TWorkSettings = {
  max_weekly_hours: number;
  workdays: number[]; // EStartOfTheWeek values
  week_start_day: number; // EStartOfTheWeek value
};
```

### Per-task rows

The timeline needs per-issue detail the API does not emit today. The `tasks` array added to each
assignee row is specified in [`phase-7.md`](phase-7.md) § "Response shape" — pinned there rather
than here because only Phases 7 and 8 consume it, but it is part of the same contract and must
not be re-invented at the frontend.

### Week bucket key (D10)

Week-granularity `period_key` returns **the ISO date of the week's first day** (`YYYY-MM-DD`),
replacing the ISO `YYYY-Www` form. Day and month keys are unchanged (`YYYY-MM-DD`, `YYYY-MM`).

## Tasks

1. Write `constants.py` with the defaults, `MAX_HOURS` re-export, and `to_plane_weekday`.
2. Write `packages/types/src/workload.ts` and export it from the package index.
3. Grep every consumer of the current week-key shape and record the hit list in this file under
   "Consumers of the week key" below — Phase 6 propagates to each.
   ```bash
   grep -rn -- "-W" packages/workload-ext/src apps/web/core/components 2>/dev/null | grep -i week
   ```

## Consumers of the week key

Ran the specified grep verbatim:

```bash
grep -rn -- "-W" packages/workload-ext/src apps/web/core/components 2>/dev/null | grep -i week
```

Zero across `packages/workload-ext/src` and `apps/web/core/components`. A broader sanity sweep of
the same two paths for `period_key`, `isocalendar`, `YYYY-Www`, and the raw `W\d\d` token also
returned zero — no frontend code parses or reconstructs the ISO-week (`YYYY-Www`) key format
today. The current frontend (`packages/workload-ext/src/*`) only ever echoes `period_key` values
back as opaque object keys (e.g. `TWorkloadRow.buckets: Record<string, number>`); it never slices
or pattern-matches the string itself. Phase 6 therefore has no in-repo consumer to migrate for
this format change — its propagation work is limited to the sibling repos (`plane-mcp-server`,
SDKs, docs) named in `CLAUDE.md`'s propagation table, which are outside this grep's scope by
design (they live in separate repos, not this worktree).

## Success criteria

- `constants.py` imports cleanly with no Django dependency (it is stdlib-only, like `aggregation.py`).
- `pnpm check` passes with the new type exported.
- The hit list above is non-empty or explicitly records `zero across <paths searched>`.
