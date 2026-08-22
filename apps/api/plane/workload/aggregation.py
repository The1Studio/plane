# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# PURE aggregation logic — stdlib only, NO Django/ORM imports.
# This is the correctness core of the workload feature and is unit-tested
# in isolation (tests/test_aggregation_pure.py), no database required.
#
# Hours are handled in integer CENTS throughout to guarantee exact
# reconciliation (largest-remainder / Hamilton distribution). Conversion
# back to float hours happens only at the API boundary.

from datetime import date, timedelta

# MAX_HOURS lives in constants.py (the leaf module) so this file can import
# to_plane_weekday from there without creating an import cycle. Re-exported
# here so existing importers (models.py, serializers.py) keep working.
from .constants import MAX_HOURS, to_plane_weekday

ALLOWED_GRANULARITIES = ("day", "week", "month")


def to_cents(hours) -> int:
    """Quantize hours to integer cents (2 dp). round() with .5-to-even is fine;
    the write path also quantizes, so stored value == cents/100."""
    return int(round(float(hours) * 100))


def from_cents(cents: int) -> float:
    return round(cents / 100.0, 2)


def quantize_hours(hours) -> float:
    """Quantize hours to 2 dp via the SAME cents rounding the aggregation uses,
    so the stored value reconciles exactly. SSOT for the write path."""
    return from_cents(to_cents(hours))


def distribute_cents(total_cents: int, n: int) -> list:
    """Largest-remainder distribution of total_cents across n days.

    Returns a list of n ints that sum EXACTLY to total_cents. Each day gets
    base = total // n; the first `rem` days get one extra cent.
    """
    if n <= 0:
        raise ValueError("n must be >= 1")
    base = total_cents // n
    rem = total_cents - base * n
    return [base + (1 if i < rem else 0) for i in range(n)]


def period_key(d: date, granularity: str, week_start_day: int) -> str:
    """Bucket key for a date. Calendar arithmetic — timezone-independent.

    `week_start_day` is a Plane `EStartOfTheWeek` value (SUNDAY=0..SATURDAY=6)
    and is REQUIRED for `week`; `day` and `month` ignore it. An arbitrary week
    start has no ISO week number (plan D10), so the week key is the ISO date
    of the containing week's first day, e.g. "2026-08-17" — not "2026-W34".
    """
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        offset = (to_plane_weekday(d) - week_start_day) % 7
        return (d - timedelta(days=offset)).isoformat()
    if granularity == "month":
        return f"{d.year:04d}-{d.month:02d}"
    raise ValueError(f"invalid granularity: {granularity!r}")


def enumerate_periods(win_from: date, win_to: date, granularity: str, week_start_day: int) -> list:
    """Every bucket key the window [win_from, win_to] covers, in sorted order.

    The counterpart to `period_key`, which maps ONE date to its bucket: this
    maps a whole window to the bucket set that window touches, so the response
    can carry a column (and therefore a capacity figure and a heat cell) for a
    period in which nobody logged an hour.

    Delegates every key to `period_key` rather than re-deriving the formats —
    the week key in particular is the containing week's first ISO date, never
    an ISO week number, and that convention must live in exactly one place.

    Callers must UNION this with the populated bucket keys, never substitute it:
    `spread_estimate` clips hours to the window but computes the key from the
    un-clipped day, so an issue starting a day or two before `win_from` can
    legitimately produce a week or month key that precedes this window's first
    key. Replacing rather than unioning would silently drop those hours from
    the heat row.

    >>> enumerate_periods(date(2026, 8, 18), date(2026, 8, 20), "day", 1)
    ['2026-08-18', '2026-08-19', '2026-08-20']
    >>> enumerate_periods(date(2026, 8, 18), date(2026, 8, 31), "week", 1)
    ['2026-08-17', '2026-08-24', '2026-08-31']
    >>> enumerate_periods(date(2026, 8, 18), date(2026, 10, 2), "month", 1)
    ['2026-08', '2026-09', '2026-10']
    """
    if win_from > win_to:
        return []
    if granularity == "day":
        n = (win_to - win_from).days
        return [(win_from + timedelta(days=i)).isoformat() for i in range(n + 1)]
    if granularity == "week":
        keys = []
        cursor = date.fromisoformat(period_key(win_from, "week", week_start_day))
        while cursor <= win_to:
            keys.append(cursor.isoformat())
            cursor += timedelta(days=7)
        return keys
    if granularity == "month":
        keys = []
        year, month = win_from.year, win_from.month
        while (year, month) <= (win_to.year, win_to.month):
            keys.append(f"{year:04d}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return keys
    raise ValueError(f"invalid granularity: {granularity!r}")


def spread_estimate(hours, start, target, win_from, win_to, granularity, workdays, week_start_day):
    """Spread one issue's hours across its [start, target] span, clipped to the
    request window [win_from, win_to].

    Returns (buckets, unscheduled_cents, dirty):
      buckets            : dict period_key -> cents (sparse; only non-empty days
                           inside the window). Per-day rate is computed on the
                           FULL span, never on the clipped window.
      unscheduled_cents  : cents that land in the Unscheduled bucket (no target).
      dirty              : True when start > target (defensive; import/partial-update).

    Semantics (plan §3.2-§3.4):
      - hours <= 0           -> excluded ({}, 0, False)
      - target is None       -> all cents unscheduled
      - start is None        -> single day on target
      - start > target       -> single day on target, dirty=True
      - span outside window  -> {} buckets, 0 unscheduled (it has a target)

    Workday-only spreading (plan D4): hours land only on days where
    `_is_workday(d, workdays)` holds, computed over the FULL [span_start,
    span_end] span — a weekend-spanning issue no longer accrues hours on
    days that carry zero capacity. If the span contains ZERO workdays, this
    falls back to spreading across every calendar day of the span (plan D9)
    so hours are never silently lost — this is a legitimate state, not an
    error. The cents/largest-remainder reconciliation is unchanged in either
    case; only the day set (and therefore `n`) changes.
    """
    cents = to_cents(hours)
    if cents <= 0:
        return {}, 0, False
    if target is None:
        return {}, cents, False

    dirty = False
    if start is None:
        span_start = span_end = target
    elif start > target:
        dirty = True
        span_start = span_end = target
    else:
        span_start, span_end = start, target

    span_days = []
    d = span_start
    while d <= span_end:
        span_days.append(d)
        d += timedelta(days=1)

    target_days = [d for d in span_days if _is_workday(d, workdays)]
    if not target_days:
        target_days = span_days  # D9: zero-workday fallback — never lose hours

    per_day = distribute_cents(cents, len(target_days))  # rate over the FULL span's workdays

    buckets = {}
    for idx, d in enumerate(target_days):
        if win_from <= d <= win_to:
            key = period_key(d, granularity, week_start_day)
            buckets[key] = buckets.get(key, 0) + per_day[idx]
    return buckets, 0, dirty


# --- capacity proration (plan D4: workday-basis, configurable workdays) ----
#
# Prior to D4, an issue's estimate spread across every CALENDAR day of its
# [start, target] span (Sat/Sun included) while capacity was prorated over a
# hardcoded Mon-Fri workweek only — a weekend-spanning issue accrued hours on
# days that carried zero capacity, so those days always read "over" even for
# a lightly-loaded member (the v1 trade-off this module used to document).
# D4 closes that mismatch: `spread_estimate` above and `capacity_for_period`
# below both honour the SAME configured `workdays` set, so hours never land
# on a day with zero capacity again (save for the D9 fallback, which is a
# deliberate, reconciled exception, not a re-introduction of the mismatch).
#
# The stored cap is a per-DAY figure (plans/260822-workload-daily-hours):
# `capacity_for_period` multiplies it by the NUMBER of workdays in a bucket
# rather than dividing a weekly total across them — algebraically identical
# to the old weekly basis when max_daily_hours == max_weekly_hours /
# len(workdays), so a workspace on the default 8h/Mon-Fri config sees
# byte-identical capacity numbers before and after the rename.


def _is_workday(d: date, workdays) -> bool:
    return to_plane_weekday(d) in workdays


def _workdays_in_month(year: int, month: int, workdays) -> int:
    """Count days in the given calendar month whose Plane weekday is in `workdays`."""
    first = date(year, month, 1)
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    span_days = (next_first - first).days
    return sum(1 for i in range(span_days) if _is_workday(first + timedelta(days=i), workdays))


def capacity_for_period(max_daily_hours, period: str, granularity: str, workdays) -> float:
    """Scale a member's per-workday capacity into one bucket's capacity, in hours.

    Pure / stdlib-only (no ORM) — unit-tested in isolation like the rest of
    this module. The basis is ONE configured workday: `max_daily_hours` is the
    capacity of a single workday, and `workdays` is used to COUNT the days in
    a bucket (guaranteed non-empty by the serializer, backstopped by the
    model's CheckConstraint) — never to divide a weekly total:
      - day   : max_daily_hours on a workday; 0.0 on a non-workday.
      - week  : max_daily_hours * len(workdays).
      - month : max_daily_hours * workdays_in_month — accounts for months with
                4 vs 5 occurrences of each weekday.
    """
    if granularity == "day":
        d = date.fromisoformat(period)
        return round(float(max_daily_hours), 2) if _is_workday(d, workdays) else 0.0
    if granularity == "week":
        return round(max_daily_hours * len(workdays), 2)
    if granularity == "month":
        year_s, month_s = period.split("-")
        n_workdays = _workdays_in_month(int(year_s), int(month_s), workdays)
        return round(max_daily_hours * n_workdays, 2)
    raise ValueError(f"invalid granularity: {granularity!r}")
