# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# PURE aggregation tests — zero Django / zero DB. Loads aggregation.py (and its
# sibling constants.py) in isolation so this runs anywhere (CI without a
# database, or `python <thisfile>`). These prove the correctness core: exact
# largest-remainder distribution, clipping, configurable workdays (D4),
# workspace-configurable week start (D10), the zero-workday fallback (D9),
# and reconciliation.
#
# This is a REWRITE of the pre-D4 pure tests, not a patch: the old tests
# asserted calendar-day spreading and ISO `YYYY-Www` week keys, both of which
# this phase replaces. Patching only the expected numbers would hide whether
# the new workday-only / configurable-week-start behaviour is actually right.

import importlib.util
import pathlib
import random
import sys
import types
from datetime import date, timedelta

_WORKLOAD_DIR = pathlib.Path(__file__).resolve().parent.parent
_PKG_NAME = "wl_pure"  # synthetic package name — see _load_pure_submodule


def _load_pure_submodule(module_name):
    """Load a stdlib-only submodule of `plane/workload/` in isolation.

    `aggregation.py` does `from .constants import ...` — a relative import
    that only resolves inside a real Python package. We cannot import the
    real `plane.workload` package for that: `plane/__init__.py` pulls in
    Celery/Django (`from .celery import app as celery_app`), which this
    PURE/stdlib-only module must run without. Instead we register a
    synthetic parent package (`wl_pure`) in `sys.modules` whose `__path__`
    points at the real `workload/` directory, and load `constants` then
    `aggregation` as its submodules — so `aggregation`'s relative import
    resolves against `wl_pure.constants`, not the real Django-coupled
    `plane.workload`.
    """
    if _PKG_NAME not in sys.modules:
        pkg = types.ModuleType(_PKG_NAME)
        pkg.__path__ = [str(_WORKLOAD_DIR)]
        sys.modules[_PKG_NAME] = pkg
    full_name = f"{_PKG_NAME}.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, _WORKLOAD_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    setattr(sys.modules[_PKG_NAME], module_name, module)
    spec.loader.exec_module(module)
    return module


const = _load_pure_submodule("constants")
agg = _load_pure_submodule("aggregation")

DEFAULT_WORKDAYS = const.DEFAULT_WORKDAYS  # Mon-Fri, Plane encoding
DEFAULT_WEEK_START_DAY = const.DEFAULT_WEEK_START_DAY  # Monday
SUN_SAT_ONLY = [0, 6]
MONDAY_ONLY = [1]
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


# --- distribution -----------------------------------------------------------

def test_distribute_sums_exact():
    for cents, n in [(1000, 3), (1000, 7), (1, 3), (999, 4), (10000, 366), (5, 5)]:
        parts = agg.distribute_cents(cents, n)
        assert len(parts) == n
        assert sum(parts) == cents, f"{cents}/{n} -> {sum(parts)}"
        assert max(parts) - min(parts) <= 1  # within one cent


def test_distribute_n1():
    assert agg.distribute_cents(1234, 1) == [1234]


def test_distribute_property_random():
    rng = random.Random(42)
    for _ in range(5000):
        cents = rng.randint(0, 1_000_000)
        n = rng.randint(1, 366)
        parts = agg.distribute_cents(cents, n)
        assert sum(parts) == cents
        assert max(parts) - min(parts) <= 1


# --- period keys --------------------------------------------------------
# Week keys are now the ISO date of the week's first day (D10) rather than
# ISO `YYYY-Www` — an arbitrary week start has no ISO week number.

def test_period_key_day():
    assert agg.period_key(date(2026, 6, 19), "day", DEFAULT_WEEK_START_DAY) == "2026-06-19"


def test_period_key_month():
    assert agg.period_key(date(2026, 6, 1), "month", DEFAULT_WEEK_START_DAY) == "2026-06"


def test_period_key_week_monday_start():
    # 2026-06-15 is a Monday. week_start_day=1 (Monday) -> the key IS that date.
    assert agg.period_key(date(2026, 6, 15), "week", 1) == "2026-06-15"
    # 2026-06-17 (Wednesday) belongs to the week starting Monday 2026-06-15.
    assert agg.period_key(date(2026, 6, 17), "week", 1) == "2026-06-15"


def test_period_key_week_start_day_changes_bucket_for_same_date():
    # Same date, two different workspace week-start configs -> different keys.
    d = date(2026, 6, 17)  # Wednesday
    assert agg.period_key(d, "week", 1) == "2026-06-15"  # Monday-start week
    assert agg.period_key(d, "week", 0) == "2026-06-14"  # Sunday-start week
    assert agg.period_key(d, "week", 1) != agg.period_key(d, "week", 0)


def test_period_key_week_equals_week_first_day_for_all_start_values():
    d = date(2026, 6, 17)  # Wednesday, plane weekday 3
    for week_start_day in range(7):
        key = agg.period_key(d, "week", week_start_day)
        first_day = date.fromisoformat(key)
        # The key IS an ISO date (format check) ...
        assert key == first_day.isoformat()
        # ... and it is <= d, within 6 days back, and itself falls exactly on
        # week_start_day (i.e. it genuinely is "the week's first day").
        assert 0 <= (d - first_day).days <= 6
        assert const.to_plane_weekday(first_day) == week_start_day


# --- spread: workday-only spreading (D4) ------------------------------------

def _sum_cents(buckets):
    return sum(buckets.values())


def test_spread_workday_only_regression_anchor():
    # Mon-Fri workdays, weekday-only span (2026-06-01..03 = Mon/Tue/Wed) ->
    # every day in the span is a workday, so this is numerically identical
    # to the pre-D4 calendar-day behaviour. Regression anchor.
    b, mb, uns, dirty = agg.spread_estimate(
        12.0, date(2026, 6, 1), date(2026, 6, 3),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert not dirty and uns == 0
    assert _sum_cents(b) == 1200
    assert b == {"2026-06-01": 400, "2026-06-02": 400, "2026-06-03": 400}
    assert mb == {"2026-06": 1200}


def test_spread_weekend_gets_zero_workday_cents_sum_to_total():
    # 2026-06-05 (Fri) .. 2026-06-08 (Mon): 4 calendar days, 2 workdays
    # (Fri + Mon). Weekend days (Sat 06, Sun 07) must NOT appear in buckets
    # at all, and the two workday cents must sum to the full total.
    b, mb, uns, dirty = agg.spread_estimate(
        8.0, date(2026, 6, 5), date(2026, 6, 8),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert not dirty and uns == 0
    assert "2026-06-06" not in b and "2026-06-07" not in b
    assert b == {"2026-06-05": 400, "2026-06-08": 400}
    assert _sum_cents(b) == 800
    assert mb == {"2026-06": 800}


def test_spread_all_weekend_d9_fallback():
    # 2026-06-06 (Sat) .. 2026-06-07 (Sun): span contains ZERO workdays under
    # Mon-Fri workdays. D9: fall back to spreading across the span's
    # calendar days rather than losing the hours.
    b, mb, uns, dirty = agg.spread_estimate(
        5.0, date(2026, 6, 6), date(2026, 6, 7),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert not dirty and uns == 0
    assert b == {"2026-06-06": 250, "2026-06-07": 250}
    assert _sum_cents(b) == 500
    assert mb == {"2026-06": 500}


def test_spread_workdays_sun_sat_only_inverse():
    # Same span as the weekend-crossing case above, but workdays=[Sun, Sat]
    # (inverse of Mon-Fri): now Fri/Mon get zero and Sat/Sun carry the hours.
    b, mb, uns, dirty = agg.spread_estimate(
        8.0, date(2026, 6, 5), date(2026, 6, 8),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        SUN_SAT_ONLY, DEFAULT_WEEK_START_DAY,
    )
    assert not dirty and uns == 0
    assert "2026-06-05" not in b and "2026-06-08" not in b
    assert b == {"2026-06-06": 400, "2026-06-07": 400}
    assert _sum_cents(b) == 800
    assert mb == {"2026-06": 800}


def test_spread_single_day_no_start():
    b, mb, uns, dirty = agg.spread_estimate(
        5.0, None, date(2026, 6, 10),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert b == {"2026-06-10": 500} and uns == 0 and not dirty
    assert mb == {"2026-06": 500}


def test_unscheduled_no_target():
    b, mb, uns, dirty = agg.spread_estimate(
        8.0, date(2026, 6, 1), None,
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert b == {} and mb == {} and uns == 800 and not dirty


def test_zero_excluded():
    assert agg.spread_estimate(
        0.0, date(2026, 6, 1), date(2026, 6, 3),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    ) == ({}, {}, 0, False)


def test_clip_partial_uses_full_span_workday_rate():
    # 8h over 2026-06-01..10 (10 calendar days) with Mon-Fri workdays = 8
    # workdays (weekends 06/07 excluded) -> rate = 100c/workday, computed on
    # the FULL span. Window sees only the first 3 days, all workdays.
    b, mb, uns, dirty = agg.spread_estimate(
        8.0, date(2026, 6, 1), date(2026, 6, 10),
        date(2026, 6, 1), date(2026, 6, 3), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert _sum_cents(b) == 300          # 3 workdays * 100c, NOT 800/10 * 3
    assert b == {"2026-06-01": 100, "2026-06-02": 100, "2026-06-03": 100}
    assert mb == {"2026-06": 300}


def test_span_entirely_outside_window():
    b, mb, uns, dirty = agg.spread_estimate(
        10.0, date(2026, 1, 1), date(2026, 1, 10),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert b == {} and mb == {} and uns == 0          # has a target -> not unscheduled


def test_leap_year_span():
    # workdays=EVERY_DAY isolates the leap-year date arithmetic from the
    # workday filter (tested separately above), matching the pre-D4 test's
    # original intent: 2024 (leap) Feb 28, 29, Mar 1 = 3 days.
    b, _mb, _, _ = agg.spread_estimate(
        9.0, date(2024, 2, 28), date(2024, 3, 1),
        date(2024, 2, 1), date(2024, 3, 31), "day",
        EVERY_DAY, DEFAULT_WEEK_START_DAY,
    )
    assert len(b) == 3 and _sum_cents(b) == 900
    # 2026 (non-leap): Feb 28, Mar 1 = 2 days.
    b2, _mb2, _, _ = agg.spread_estimate(
        9.0, date(2026, 2, 28), date(2026, 3, 1),
        date(2026, 2, 1), date(2026, 3, 31), "day",
        EVERY_DAY, DEFAULT_WEEK_START_DAY,
    )
    assert len(b2) == 2 and _sum_cents(b2) == 900


def test_dirty_start_after_target():
    b, mb, uns, dirty = agg.spread_estimate(
        6.0, date(2026, 6, 10), date(2026, 6, 1),
        date(2026, 6, 1), date(2026, 6, 30), "day",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert dirty is True
    assert b == {"2026-06-01": 600} and uns == 0
    assert mb == {"2026-06": 600}


def test_reconciliation_window_contains_span():
    # Awkward division 100h/7d across a week, window contains the whole span.
    # All 7 days of the span are Mon-Fri workdays only for 5 of them... use
    # EVERY_DAY so the full 100h is guaranteed to land inside the ONE week
    # bucket regardless of the workday filter, isolating the aggregation
    # (multiple days -> one key) from the workday-filtering behaviour.
    b, mb, uns, dirty = agg.spread_estimate(
        100.0, date(2026, 6, 1), date(2026, 6, 7),
        date(2026, 1, 1), date(2026, 12, 31), "week",
        EVERY_DAY, DEFAULT_WEEK_START_DAY,
    )
    assert _sum_cents(b) + uns == 10000  # exact
    assert set(b.keys()) == {"2026-06-01"}  # Monday-start week, all 7 days in one bucket
    assert mb == {"2026-06": 10000}      # calendar month, independent of the week key above


def test_spread_sum_reconciliation_property_random():
    # For random spans fully inside the window, sum(buckets) + unscheduled
    # must equal to_cents(hours) exactly, across every workdays/week_start
    # configuration and every granularity — proving the D4/D9 rewrite never
    # drops or duplicates a cent, only relocates which day/bucket it lands in.
    # month_buckets is checked too: it must reconcile to the SAME total as
    # buckets (both are clipped identically; only the key differs).
    rng = random.Random(7)
    workday_sets = [DEFAULT_WORKDAYS, SUN_SAT_ONLY, MONDAY_ONLY, EVERY_DAY]
    granularities = ["day", "week", "month"]
    for _ in range(2000):
        start = date(rng.randint(2020, 2032), rng.randint(1, 12), rng.randint(1, 28))
        span_len = rng.randint(0, 60)
        target = start + timedelta(days=span_len)
        hours = rng.uniform(0.01, 500)
        workdays = rng.choice(workday_sets)
        week_start_day = rng.randint(0, 6)
        granularity = rng.choice(granularities)
        win_from = start - timedelta(days=10)
        win_to = target + timedelta(days=10)  # window strictly contains the span
        b, mb, uns, dirty = agg.spread_estimate(
            hours, start, target, win_from, win_to, granularity,
            workdays, week_start_day,
        )
        assert _sum_cents(b) + uns == agg.to_cents(hours), (
            f"start={start} target={target} hours={hours} workdays={workdays} "
            f"week_start_day={week_start_day} granularity={granularity}"
        )
        assert _sum_cents(mb) == _sum_cents(b), (
            f"month_buckets/buckets disagree on total: start={start} target={target} "
            f"hours={hours} workdays={workdays} week_start_day={week_start_day} "
            f"granularity={granularity}"
        )


# --- month_buckets: calendar-month accumulation (plan D6) -------------------
#
# `buckets` is keyed at the REQUESTED granularity; `month_buckets` is ALWAYS
# keyed at calendar-month granularity, independent of `granularity` — this is
# what makes the month/quarter badge exact even when a `week` bucket straddles
# a month boundary.

def test_spread_month_boundary_straddle_buckets_vs_month_buckets():
    # 2026-08-31 (Mon) .. 2026-09-04 (Fri): a single Mon-Fri workweek, so at
    # granularity="week" every day lands in ONE week bucket keyed 2026-08-31
    # (Monday-start). But calendar-month-wise, Aug 31 is one day in August
    # and Sep 1-4 are four days in September — month_buckets MUST split them
    # while buckets stays a single entry. This is the whole point of D6: the
    # week-attribution bug this replaces would have put all 5 days' hours
    # into August via `buckets`, and a naive "copy buckets" month_buckets
    # would inherit exactly that bug.
    b, mb, uns, dirty = agg.spread_estimate(
        50.0, date(2026, 8, 31), date(2026, 9, 4),
        date(2026, 8, 1), date(2026, 9, 30), "week",
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert not dirty and uns == 0
    # buckets: one week bucket, all 5 days' hours (10.0h/day * 5 = 50.0h = 5000c).
    assert set(b.keys()) == {"2026-08-31"}
    assert _sum_cents(b) == 5000
    # month_buckets: split 1 day in August, 4 days in September.
    assert mb == {"2026-08": 1000, "2026-09": 4000}
    # Neither map loses a cent, and NEITHER is a copy of the other — proving
    # this test actually distinguishes the two (a `month_buckets = dict(buckets)`
    # bug would make this assertion fail: b has ONE key, mb has TWO).
    assert set(b.keys()) != set(mb.keys())
    assert _sum_cents(mb) == _sum_cents(b) == 5000


def test_spread_month_buckets_respects_the_window_clip():
    # Same boundary-straddling span as above, but the request window
    # (win_from, win_to) only covers August — September 1-4 must be clipped
    # out of BOTH buckets and month_buckets identically, same as `buckets`
    # already does for a window that doesn't cover the whole span.
    b, mb, uns, dirty = agg.spread_estimate(
        50.0, date(2026, 8, 31), date(2026, 9, 4),
        date(2026, 8, 1), date(2026, 8, 31), "week",  # window ends Aug 31
        DEFAULT_WORKDAYS, DEFAULT_WEEK_START_DAY,
    )
    assert not dirty and uns == 0
    # Only Aug 31 (1 day) is inside the window; Sep 1-4 (4 days) are clipped.
    assert set(b.keys()) == {"2026-08-31"}
    assert _sum_cents(b) == 1000
    assert mb == {"2026-08": 1000}
    assert "2026-09" not in mb


# --- capacity proration (plans/260822-workload-daily-hours: daily basis) ----
#
# `capacity_for_period`'s first argument is now the capacity of ONE workday
# (`max_daily_hours`); `workdays` COUNTS the days in a bucket rather than
# dividing a weekly total across them.

def test_capacity_day_workday():
    # 2026-06-15 is a Monday.
    assert agg.capacity_for_period(8.0, "2026-06-15", "day", DEFAULT_WORKDAYS) == 8.0


def test_capacity_day_weekend_is_zero():
    # 2026-06-13/14 are Sat/Sun.
    assert agg.capacity_for_period(8.0, "2026-06-13", "day", DEFAULT_WORKDAYS) == 0.0
    assert agg.capacity_for_period(8.0, "2026-06-14", "day", DEFAULT_WORKDAYS) == 0.0


def test_capacity_day_single_workday_equals_max_daily_hours():
    # workdays=[Monday] no longer changes the day branch at all — the day
    # figure is always the configured daily cap on a workday, regardless of
    # how many workdays are configured.
    assert agg.capacity_for_period(40.0, "2026-06-15", "day", MONDAY_ONLY) == 40.0  # Monday
    assert agg.capacity_for_period(40.0, "2026-06-16", "day", MONDAY_ONLY) == 0.0   # Tuesday


def test_capacity_week_multiplies_by_len_workdays():
    # Week granularity doesn't parse `period` at all; pass a D10-shaped
    # date-string week key to reflect the new format (functionally unused).
    assert agg.capacity_for_period(7.5, "2026-06-15", "week", DEFAULT_WORKDAYS) == 37.5


def test_capacity_month_basic():
    # June 2026 starts on a Monday, 30 days -> 22 Mon-Fri workdays (4 full
    # Mon-Fri weeks + the trailing Mon/Tue of the 5th week).
    assert agg.capacity_for_period(8.0, "2026-06", "month", DEFAULT_WORKDAYS) == 176.0


def test_capacity_month_4_vs_5_occurrence():
    # workdays=[Monday] isolates the "N occurrences of one weekday in a
    # month" effect cleanly: June 2026 has 5 Mondays, July 2026 has 4.
    assert agg.capacity_for_period(40.0, "2026-06", "month", MONDAY_ONLY) == 200.0  # 40 * 5
    assert agg.capacity_for_period(40.0, "2026-07", "month", MONDAY_ONLY) == 160.0  # 40 * 4


def test_capacity_month_second_data_point():
    # December 2026: 31 days, 8 weekend days -> 23 Mon-Fri workdays.
    assert agg.capacity_for_period(8.0, "2026-12", "month", DEFAULT_WORKDAYS) == 184.0


def test_capacity_scales_linearly_with_daily_hours():
    assert agg.capacity_for_period(0.0, "2026-06-15", "day", DEFAULT_WORKDAYS) == 0.0
    assert agg.capacity_for_period(2.0, "2026-06-15", "day", DEFAULT_WORKDAYS) == 2.0


def test_capacity_invalid_granularity_raises():
    try:
        agg.capacity_for_period(8.0, "2026-06-15", "year", DEFAULT_WORKDAYS)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- regression anchor: daily basis == old weekly basis for the default ----
#
# This is phase-1.md's real bar. `max_daily_hours == max_weekly_hours /
# len(workdays)` must produce numbers byte-identical to the old weekly-basis
# call, for the default Mon-Fri config, across all three granularities and
# across a 21-workday and a 23-workday month. Expected month values are
# hand-counted below, never derived from `_workdays_in_month` itself.

def test_capacity_daily_basis_matches_old_weekly_basis_for_default_config():
    OLD_MAX_WEEKLY_HOURS = 40.0
    NEW_MAX_DAILY_HOURS = 8.0  # == 40.0 / len(DEFAULT_WORKDAYS) == 40.0 / 5

    # day: a workday is 8.0h either way; a non-workday is 0.0h either way.
    assert agg.capacity_for_period(NEW_MAX_DAILY_HOURS, "2026-08-17", "day", DEFAULT_WORKDAYS) == 8.0   # Monday
    assert agg.capacity_for_period(NEW_MAX_DAILY_HOURS, "2026-08-22", "day", DEFAULT_WORKDAYS) == 0.0   # Saturday
    assert agg.capacity_for_period(NEW_MAX_DAILY_HOURS, "2026-08-23", "day", DEFAULT_WORKDAYS) == 0.0   # Sunday

    # week: old = max_weekly_hours as-is; new = max_daily_hours * len(workdays).
    assert agg.capacity_for_period(NEW_MAX_DAILY_HOURS, "2026-08-17", "week", DEFAULT_WORKDAYS) == OLD_MAX_WEEKLY_HOURS

    # month: 2026-08 (August) has 21 Mon-Fri workdays (hand-counted: 31 days,
    # starts on a Saturday, 4 full Mon-Fri weeks + a trailing Mon/Tue/Wed/Thu/Fri
    # in the last partial week = 21). 2026-09 (September) has 22 Mon-Fri
    # workdays (hand-counted: 30 days, starts on a Tuesday, 4 full Mon-Fri
    # weeks + a trailing Tue/Wed/Thu/Fri/... — 22 in total).
    #
    # NOTE: phase-1.md's worked example cites 21/168 for August and 22/176
    # for September; the 168 = 8 * 21 and 176 = 8 * 22 figures below match
    # that table exactly.
    assert agg.capacity_for_period(NEW_MAX_DAILY_HOURS, "2026-08", "month", DEFAULT_WORKDAYS) == 168.0
    assert agg.capacity_for_period(NEW_MAX_DAILY_HOURS, "2026-09", "month", DEFAULT_WORKDAYS) == 176.0

    # A third data point with a 23-workday month: December 2026 (hand-counted
    # above in test_capacity_month_second_data_point: 31 days, 8 weekend days
    # -> 23 Mon-Fri workdays). old = 40 * (23/5) = 184.0; new = 8 * 23 = 184.0.
    assert agg.capacity_for_period(NEW_MAX_DAILY_HOURS, "2026-12", "month", DEFAULT_WORKDAYS) == 184.0


# --- enumerate_periods (window-complete columns) ----------------------------
#
# The counterpart to period_key. These pin the property that made the badge
# wrong before it existed: the response's column set must be a function of the
# REQUESTED WINDOW, not of which buckets happened to receive hours.

def test_enumerate_periods_day_is_every_calendar_day_inclusive():
    keys = agg.enumerate_periods(date(2026, 8, 18), date(2026, 8, 20), "day", DEFAULT_WEEK_START_DAY)
    assert keys == ["2026-08-18", "2026-08-19", "2026-08-20"]


def test_enumerate_periods_single_day_window():
    for gran, expected in (("day", ["2026-08-18"]), ("week", ["2026-08-17"]), ("month", ["2026-08"])):
        keys = agg.enumerate_periods(date(2026, 8, 18), date(2026, 8, 18), gran, DEFAULT_WEEK_START_DAY)
        assert keys == expected, (gran, keys)


def test_enumerate_periods_week_starts_at_the_containing_week_not_the_window():
    # Aug 18 2026 is a Tuesday; with a Monday week start its bucket is Aug 17,
    # which precedes the window. The first key MUST be that bucket, otherwise
    # hours keyed to it would have no capacity entry and no heat cell.
    keys = agg.enumerate_periods(date(2026, 8, 18), date(2026, 8, 31), "week", DEFAULT_WEEK_START_DAY)
    assert keys == ["2026-08-17", "2026-08-24", "2026-08-31"]


def test_enumerate_periods_week_honours_week_start_day():
    sunday_start = agg.enumerate_periods(date(2026, 8, 18), date(2026, 8, 25), "week", 0)
    assert sunday_start == ["2026-08-16", "2026-08-23"]
    monday_start = agg.enumerate_periods(date(2026, 8, 18), date(2026, 8, 25), "week", 1)
    assert monday_start == ["2026-08-17", "2026-08-24"]


def test_enumerate_periods_month_crosses_a_year_boundary():
    keys = agg.enumerate_periods(date(2026, 11, 20), date(2027, 2, 3), "month", DEFAULT_WEEK_START_DAY)
    assert keys == ["2026-11", "2026-12", "2027-01", "2027-02"]


def test_enumerate_periods_every_key_agrees_with_period_key():
    # The two must never drift: every day in the window must land in a bucket
    # this function already listed.
    win_from, win_to = date(2026, 8, 18), date(2026, 11, 10)
    for gran in ("day", "week", "month"):
        listed = set(agg.enumerate_periods(win_from, win_to, gran, DEFAULT_WEEK_START_DAY))
        d = win_from
        while d <= win_to:
            assert agg.period_key(d, gran, DEFAULT_WEEK_START_DAY) in listed, (gran, d)
            d += timedelta(days=1)


def test_enumerate_periods_covers_the_reported_window():
    # The regression this whole change exists for: Aug 18 - Nov 10 2026 at week
    # granularity is 13 columns. The old code emitted only the populated ones,
    # which on the reported workspace was 3 -> a "120h" capacity denominator.
    keys = agg.enumerate_periods(date(2026, 8, 18), date(2026, 11, 10), "week", DEFAULT_WEEK_START_DAY)
    assert len(keys) == 13
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_enumerate_periods_inverted_window_is_empty_not_an_error():
    assert agg.enumerate_periods(date(2026, 8, 20), date(2026, 8, 18), "day", DEFAULT_WEEK_START_DAY) == []


def test_enumerate_periods_rejects_bad_granularity():
    try:
        agg.enumerate_periods(date(2026, 8, 18), date(2026, 8, 20), "fortnight", DEFAULT_WEEK_START_DAY)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an invalid granularity")


def _main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_main())
