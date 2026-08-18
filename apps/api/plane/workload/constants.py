# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork (workspace work settings) — shared contract for the workload
# app's workspace-wide settings feature (plans/260818-workload-workspace-settings).
#
# PURE — stdlib only, NO Django/ORM imports. Mirrors aggregation.py's isolation
# constraint so this module can be imported (and unit-tested) with no database
# and no Django app registry.
#
# Weekday encoding
# -----------------
# Exactly ONE convention crosses the API boundary: Plane's `EStartOfTheWeek`
# TypeScript enum (packages/types/src/workload.ts / users.ts), which encodes
# SUNDAY=0 .. SATURDAY=6. Storage (WorkloadSettings.workdays / week_start_day)
# and every response payload use that encoding.
#
# Python's `date.weekday()` uses the opposite origin (MONDAY=0 .. SUNDAY=6).
# `to_plane_weekday()` is the ONLY place the two conventions meet — nothing
# else in this codebase should re-derive this mapping.

from datetime import date

__all__ = [
    "MAX_HOURS",
    "DEFAULT_MAX_WEEKLY_HOURS",
    "DEFAULT_WORKDAYS",
    "DEFAULT_WEEK_START_DAY",
    "to_plane_weekday",
]


def to_plane_weekday(d: date) -> int:
    """Convert a stdlib date's Python weekday (Mon=0..Sun=6) to Plane's
    EStartOfTheWeek encoding (Sun=0..Sat=6).

    >>> to_plane_weekday(date(2026, 8, 17))  # Monday
    1
    >>> to_plane_weekday(date(2026, 8, 18))  # Tuesday
    2
    >>> to_plane_weekday(date(2026, 8, 22))  # Saturday
    6
    >>> to_plane_weekday(date(2026, 8, 23))  # Sunday
    0
    """
    return (d.weekday() + 1) % 7


# Single source of truth for the per-issue hours bound, consumed by the model,
# the serializer and aggregation.py. Defined HERE rather than re-exported from
# aggregation.py: aggregation imports `to_plane_weekday` from this module, so a
# re-export would make the two modules mutually dependent — and because
# aggregation's import block sits above its own assignments, that cycle raises
# ImportError on whichever module loads first. constants.py is the leaf.
MAX_HOURS = 10000


# --- Defaults ---------------------------------------------------------------
# Applied when a workspace has no WorkloadSettings row yet — callers never
# branch on absence; the API always returns these values in that case.

DEFAULT_MAX_WEEKLY_HOURS = 40.0

# Mon-Fri in Plane encoding (SUNDAY=0 .. SATURDAY=6).
DEFAULT_WORKDAYS = [1, 2, 3, 4, 5]

# Monday, NOT Sunday (core's per-user default). Today's week buckets are ISO
# weeks (aggregation.py:56-58, always Monday-start), so Monday is the value
# that leaves existing workspaces' week columns unchanged on migration.
DEFAULT_WEEK_START_DAY = 1


# --- Self-verification (module-load-time assertions) ------------------------
# A doctest alone can silently bit-rot if the test suite never runs
# `python -m doctest` on this file. These assertions run on every import
# (including a bare `python -c "import ...constants"` sanity check) and prove
# the mapping for a known date/weekday pair, per phase-0.md's requirement to
# verify the encoding before considering it done.

assert to_plane_weekday(date(2026, 8, 17)) == 1  # Monday   -> MONDAY
assert to_plane_weekday(date(2026, 8, 18)) == 2  # Tuesday  -> TUESDAY
assert to_plane_weekday(date(2026, 8, 19)) == 3  # Wednesday-> WEDNESDAY
assert to_plane_weekday(date(2026, 8, 20)) == 4  # Thursday -> THURSDAY
assert to_plane_weekday(date(2026, 8, 21)) == 5  # Friday   -> FRIDAY
assert to_plane_weekday(date(2026, 8, 22)) == 6  # Saturday -> SATURDAY
assert to_plane_weekday(date(2026, 8, 23)) == 0  # Sunday   -> SUNDAY
