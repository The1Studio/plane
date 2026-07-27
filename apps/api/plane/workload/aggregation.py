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

ALLOWED_GRANULARITIES = ("day", "week", "month")

# Single source of truth for the per-issue hours bound (model + serializer).
MAX_HOURS = 10000


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


def period_key(d: date, granularity: str) -> str:
    """Bucket key for a date. Calendar arithmetic — timezone-independent.
    Week uses ISO year+week so 2026-12-31 -> '2027-W01'."""
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        iso = d.isocalendar()  # (iso_year, iso_week, iso_weekday)
        return f"{iso[0]}-W{iso[1]:02d}"
    if granularity == "month":
        return f"{d.year:04d}-{d.month:02d}"
    raise ValueError(f"invalid granularity: {granularity!r}")


def spread_estimate(hours, start, target, win_from, win_to, granularity):
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

    n = (span_end - span_start).days + 1
    per_day = distribute_cents(cents, n)  # rate over the FULL span

    ov_start = max(span_start, win_from)
    ov_end = min(span_end, win_to)

    buckets = {}
    if ov_start <= ov_end:
        d = span_start
        idx = 0
        while d <= span_end:
            if ov_start <= d <= ov_end:
                key = period_key(d, granularity)
                buckets[key] = buckets.get(key, 0) + per_day[idx]
            d += timedelta(days=1)
            idx += 1
    return buckets, 0, dirty


# --- capacity proration (plan D-B1: workday-basis, weekly / 5) -------------
#
# ⚠ Mismatch with spread_estimate above: an issue's estimate is spread across
# every CALENDAR day of its [start, target] span (Sat/Sun included), while
# capacity below is prorated over WORKDAYS only (Mon-Fri; weekends = 0). A
# weekend-spanning issue therefore accrues hours on days that carry zero
# capacity — those days will always read "over" in the daily bucket even for
# a lightly-loaded member. This is a deliberate v1 trade-off (plan D-B1/R2),
# not a bug: the day-granularity "over" signal is noisiest at weekends, but
# week/month buckets (which don't hit this mismatch) are the primary signal.

_WORKWEEK_DAYS = 5  # Mon-Fri


def _is_workday(d: date) -> bool:
    return d.weekday() < _WORKWEEK_DAYS  # Mon=0 .. Fri=4, Sat=5, Sun=6


def _workdays_in_month(year: int, month: int) -> int:
    """Count Mon-Fri days in the given calendar month."""
    first = date(year, month, 1)
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    span_days = (next_first - first).days
    return sum(1 for i in range(span_days) if _is_workday(first + timedelta(days=i)))


def capacity_for_period(weekly_hours, period: str, granularity: str) -> float:
    """Prorate a member's weekly capacity into one bucket's capacity, in hours.

    Pure / stdlib-only (no ORM) — unit-tested in isolation like the rest of
    this module. Basis is ÷5 workdays (plan D-B1):
      - day   : weekly_hours / 5 on a workday (Mon-Fri); 0 on Sat/Sun.
      - week  : weekly_hours as-is (one ISO week = one full capacity unit).
      - month : weekly_hours * (workdays_in_month / 5) — accounts for months
                with 4 vs 5 occurrences of each weekday.
    """
    if granularity == "day":
        d = date.fromisoformat(period)
        return round(weekly_hours / _WORKWEEK_DAYS, 2) if _is_workday(d) else 0.0
    if granularity == "week":
        return round(float(weekly_hours), 2)
    if granularity == "month":
        year_s, month_s = period.split("-")
        workdays = _workdays_in_month(int(year_s), int(month_s))
        return round(weekly_hours * (workdays / _WORKWEEK_DAYS), 2)
    raise ValueError(f"invalid granularity: {granularity!r}")
