# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# PURE aggregation tests — zero Django / zero DB. Loads aggregation.py in
# isolation so it runs anywhere (CI without a database, or `python <thisfile>`).
# These prove the correctness core: exact largest-remainder distribution,
# clipping, ISO-week keys, leap year, reconciliation.

import importlib.util
import pathlib
import random
from datetime import date

_AGG_PATH = pathlib.Path(__file__).resolve().parent.parent / "aggregation.py"
_spec = importlib.util.spec_from_file_location("wl_aggregation", _AGG_PATH)
agg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agg)


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


# --- period keys ------------------------------------------------------------

def test_period_key_day():
    assert agg.period_key(date(2026, 6, 19), "day") == "2026-06-19"


def test_period_key_month():
    assert agg.period_key(date(2026, 6, 1), "month") == "2026-06"


def test_period_key_week_monday():
    # 2026-06-15 is a Monday → ISO week 25.
    assert agg.period_key(date(2026, 6, 15), "week") == "2026-W25"


def test_period_key_iso_year_boundary():
    # 2018-12-31 (a Monday) belongs to ISO week 1 of 2019 — the classic
    # ISO-year vs calendar-year mismatch. Keyed by ISO year, not 2018.
    assert agg.period_key(date(2018, 12, 31), "week") == "2019-W01"
    # And 2021-01-01 belongs to ISO week 53 of 2020.
    assert agg.period_key(date(2021, 1, 1), "week") == "2020-W53"


# --- spread -----------------------------------------------------------------

def _sum_cents(buckets):
    return sum(buckets.values())


def test_spread_even_full_window():
    b, uns, dirty = agg.spread_estimate(
        12.0, date(2026, 6, 1), date(2026, 6, 3),
        date(2026, 6, 1), date(2026, 6, 30), "day",
    )
    assert not dirty and uns == 0
    assert _sum_cents(b) == 1200          # exact reconciliation
    assert b == {"2026-06-01": 400, "2026-06-02": 400, "2026-06-03": 400}


def test_spread_single_day_no_start():
    b, uns, dirty = agg.spread_estimate(
        5.0, None, date(2026, 6, 10),
        date(2026, 6, 1), date(2026, 6, 30), "day",
    )
    assert b == {"2026-06-10": 500} and uns == 0 and not dirty


def test_unscheduled_no_target():
    b, uns, dirty = agg.spread_estimate(
        8.0, date(2026, 6, 1), None,
        date(2026, 6, 1), date(2026, 6, 30), "day",
    )
    assert b == {} and uns == 800 and not dirty


def test_zero_excluded():
    assert agg.spread_estimate(
        0.0, date(2026, 6, 1), date(2026, 6, 3),
        date(2026, 6, 1), date(2026, 6, 30), "day",
    ) == ({}, 0, False)


def test_clip_partial_uses_full_span_rate():
    # 10h over 10 days = 100 cents/day. Window sees only 3 of those days.
    b, uns, dirty = agg.spread_estimate(
        10.0, date(2026, 6, 1), date(2026, 6, 10),
        date(2026, 6, 1), date(2026, 6, 3), "day",
    )
    assert _sum_cents(b) == 300          # 3 days * 100c, NOT 1000/3
    assert all(v == 100 for v in b.values())


def test_span_entirely_outside_window():
    b, uns, dirty = agg.spread_estimate(
        10.0, date(2026, 1, 1), date(2026, 1, 10),
        date(2026, 6, 1), date(2026, 6, 30), "day",
    )
    assert b == {} and uns == 0          # has a target → not unscheduled


def test_leap_year_span():
    # 2024 is a leap year: Feb 28, 29, Mar 1 = 3 days.
    b, _, _ = agg.spread_estimate(
        9.0, date(2024, 2, 28), date(2024, 3, 1),
        date(2024, 2, 1), date(2024, 3, 31), "day",
    )
    assert len(b) == 3 and _sum_cents(b) == 900
    # 2026 (non-leap): Feb 28, Mar 1 = 2 days.
    b2, _, _ = agg.spread_estimate(
        9.0, date(2026, 2, 28), date(2026, 3, 1),
        date(2026, 2, 1), date(2026, 3, 31), "day",
    )
    assert len(b2) == 2 and _sum_cents(b2) == 900


def test_dirty_start_after_target():
    b, uns, dirty = agg.spread_estimate(
        6.0, date(2026, 6, 10), date(2026, 6, 1),
        date(2026, 6, 1), date(2026, 6, 30), "day",
    )
    assert dirty is True
    assert b == {"2026-06-01": 600} and uns == 0


def test_reconciliation_window_contains_span():
    # Awkward division 100h/7d across weeks, window contains the whole span.
    b, uns, dirty = agg.spread_estimate(
        100.0, date(2026, 6, 1), date(2026, 6, 7),
        date(2026, 1, 1), date(2026, 12, 31), "week",
    )
    assert _sum_cents(b) + uns == 10000  # exact


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
    import sys
    sys.exit(_main())
