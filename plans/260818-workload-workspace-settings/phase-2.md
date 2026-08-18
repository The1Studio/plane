# Phase 2 — Aggregation core: workdays + week start

**Goal:** make the pure aggregation module honour configurable workdays and week start.
Depends on Phase 0 only (it consumes the contract, not the model). Runs concurrently with Phase 1.

Parent plan: [`plan.md`](plan.md). Contract: [`phase-0.md`](phase-0.md).

## Ownership

- `apps/api/plane/workload/aggregation.py`
- `apps/api/plane/workload/tests/test_aggregation_pure.py`

`aggregation.py` is **stdlib-only** — no Django, no ORM. That property is why it is unit-testable
without a database and must be preserved: settings arrive as plain arguments, never as a model.

## Changes

### 1. `period_key(d, granularity, week_start_day)` — week-start-aware

Today: `d.isocalendar()` → `"2026-W34"` (always Monday-start, `aggregation.py:56-58`).

New: for `week`, return the ISO date of the containing week's first day (D10):

```python
offset = (to_plane_weekday(d) - week_start_day) % 7
return (d - timedelta(days=offset)).isoformat()
```

Day and month branches are unchanged. `week_start_day` is required for `week`; day/month ignore it.

### 2. `_is_workday(d, workdays)` — configurable

Replaces the hardcoded `d.weekday() < 5` (`aggregation.py:130`):

```python
return to_plane_weekday(d) in workdays
```

`_WORKWEEK_DAYS = 5` is deleted. Every divisor becomes `len(workdays)`, which the Phase 1
serializer guarantees is ≥ 1.

### 3. `_workdays_in_month(year, month, workdays)` — configurable

Same signature change; counts days whose Plane weekday is in `workdays`.

### 4. `capacity_for_period(max_weekly_hours, period, granularity, workdays)`

| Granularity | New formula |
|---|---|
| `day` | `max_weekly_hours / len(workdays)` on a workday, else `0.0` |
| `week` | `max_weekly_hours` as-is |
| `month` | `max_weekly_hours * (workdays_in_month / len(workdays))` |

Note the `day` branch now parses a plain `YYYY-MM-DD` for both day and week granularity — the
week key is a date string, so the existing `date.fromisoformat(period)` call still works for week.

### 5. `spread_estimate(...)` — workday-only spreading (D4)

**This is the behaviour change with the widest blast radius.** Today hours spread across every
calendar day of `[start, target]` (`aggregation.py:63-113`), which is why weekend buckets always
read "over" (the artefact documented at `aggregation.py:115-124`). That comment block is deleted
with the behaviour it describes.

New algorithm:

1. Build `span_days` = every date in `[span_start, span_end]`.
2. `target_days` = `[d for d in span_days if _is_workday(d, workdays)]`.
3. **If `target_days` is empty → fall back to `span_days`** (D9). Hours are never lost when an
   issue is scheduled entirely across non-workdays. Log nothing; this is a legitimate state.
4. `per_day = distribute_cents(cents, len(target_days))` — the rate is computed over the FULL
   span's workdays, then clipped to the request window, exactly as today.
5. Accumulate into buckets only for `target_days` inside `[win_from, win_to]`.

The cents/largest-remainder reconciliation is unchanged — only `n` and the day set change.

## Test rewrite

The existing pure tests assert calendar-day distribution and ISO week keys. They are **rewritten,
not patched** — patching expected numbers hides whether the new behaviour is right.

Required cases:

- Mon–Fri workdays, weekday-only span → unchanged from today (regression anchor).
- Span crossing a weekend → weekend days get **zero**, weekday cents sum to the full total.
- Span entirely on a weekend → D9 fallback spreads across those days; total reconciles.
- `workdays=[0,6]` (Sun+Sat only) → inverse of the above.
- `workdays=[1]` (Monday only) → `capacity_for_period` day branch equals `max_weekly_hours`.
- `week_start_day=0` (Sunday) vs `1` (Monday) → same date lands in different week keys.
- Week key format is `YYYY-MM-DD` and equals the week's first day for all 7 start values.
- Month capacity across a 4- vs 5-occurrence month.
- Sum-reconciliation property test: for random spans, `sum(buckets.values()) + unscheduled ==
  to_cents(hours)` whenever the span is inside the window.

## Success criteria

- `aggregation.py` still imports with **zero** Django/ORM imports.
- Full pure-test suite green with no golden-file diffing.
- `grep -n "_WORKWEEK_DAYS\|isocalendar" aggregation.py` returns nothing.
