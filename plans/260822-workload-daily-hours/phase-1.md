# Phase 1 — Backend: hour cap becomes per-day

**Plan:** [`plan.md`](plan.md) — read its "The contract (pinned)" section before writing code.
**Depends on:** nothing. **Blocks:** Phase 2.
**Effort:** M (~5.5h)

Self-contained: everything needed to start is in this file plus `plan.md`'s contract table.

---

## Goal

`WorkloadSettings.max_weekly_hours` (default `40.0`) becomes `max_daily_hours`
(default `8.0`) across the model, both API surfaces and the pure capacity math, with
**no change in computed output** for a workspace on the default config.

---

## File ownership (this phase owns these and nothing else)

```
apps/api/plane/workload/constants.py
apps/api/plane/workload/models.py
apps/api/plane/workload/migrations/0006_workloadsettings_max_daily_hours.py   (new)
apps/api/plane/workload/aggregation.py
apps/api/plane/workload/serializers.py
apps/api/plane/workload/views.py
apps/api/plane/workload/service.py
apps/api/plane/workload/tests/test_work_settings.py
apps/api/plane/workload/tests/test_workload_db.py
apps/api/plane/workload/tests/test_aggregation_pure.py
```

Do NOT touch `api_views.py` — it delegates to the shared `settings_get` / `settings_put`
handlers in `views.py` and contains no reference to the renamed field (verified).
Do NOT touch `migrations/0003`/`0004` — historical migrations are frozen; `0004` carries its
own frozen copy of the old default and must keep it (a historical migration that imports a
live constant breaks the moment the constant changes).

---

## Steps

### 1.1 — `constants.py`

- `DEFAULT_MAX_WEEKLY_HOURS = 40.0` → `DEFAULT_MAX_DAILY_HOURS = 8.0`.
- Update the `__all__` entry.
- Update the `--- Defaults ---` comment block: the value applied when a workspace has no
  `WorkloadSettings` row is now a **daily** cap.
- Leave `MAX_HOURS`, `DEFAULT_WORKDAYS`, `DEFAULT_WEEK_START_DAY`, `to_plane_weekday()` and
  every module-load assertion untouched. The weekday encoding is not part of this change.

### 1.2 — `models.py`

- Import `DEFAULT_MAX_DAILY_HOURS` instead of `DEFAULT_MAX_WEEKLY_HOURS`.
- `max_weekly_hours = models.FloatField(default=DEFAULT_MAX_WEEKLY_HOURS, ...)` →
  `max_daily_hours = models.FloatField(default=DEFAULT_MAX_DAILY_HOURS, ...)`. Validators
  (`MinValueValidator(0)`, `MaxValueValidator(MAX_HOURS)`) are unchanged — see plan D4.
- Update the class docstring's first line and `__str__`.
- Leave both `CheckConstraint`s exactly as they are. `ck_workload_settings_workdays_nonempty`
  is still load-bearing: the `week` capacity branch multiplies by `len(workdays)`.

### 1.3 — Migration `0006`

New file `migrations/0006_workloadsettings_max_daily_hours.py`.

Per plan **D1 (reset, do not convert)**, this is a drop-and-add, not a `RenameField`:

```python
operations = [
    migrations.RemoveField(model_name="workloadsettings", name="max_weekly_hours"),
    migrations.AddField(
        model_name="workloadsettings",
        name="max_daily_hours",
        field=models.FloatField(
            default=8.0,
            validators=[MinValueValidator(0), MaxValueValidator(10000)],
        ),
    ),
]
```

Requirements:

- **Hardcode `8.0` and `10000` as literals.** Do NOT import `DEFAULT_MAX_DAILY_HOURS` or
  `MAX_HOURS` from `constants.py` — a migration is a historical record and must not re-derive
  itself from a live constant that will change again.
- Add a module docstring stating: this drops the weekly value rather than converting it
  (user decision D1, 2026-08-22); an admin who had customised the weekly cap re-enters it in
  the new daily unit via the workspace settings UI.
- Record the recovery query in that docstring so pre-migration values remain retrievable from
  a backup: `SELECT workspace_id, max_weekly_hours FROM workload_settings;`
- **Do not add `RenameField`.** Drop-and-add is what makes the reset explicit and total;
  a rename followed by a data migration would express the same outcome less legibly.

### 1.4 — `aggregation.py` — the arithmetic

Rename the first parameter of `capacity_for_period` to `max_daily_hours` and rewrite the
three branches per `plan.md`'s contract table:

| granularity | new expression                                                          |
| ----------- | ----------------------------------------------------------------------- |
| `day`       | `round(float(max_daily_hours), 2)` on a workday, else `0.0`             |
| `week`      | `round(max_daily_hours * len(workdays), 2)`                             |
| `month`     | `round(max_daily_hours * _workdays_in_month(year, month, workdays), 2)` |

- `_is_workday()` and `_workdays_in_month()` are unchanged.
- Rewrite the function docstring's basis explanation: the basis is now one configured
  workday, and `workdays` is used to COUNT days per bucket rather than to divide a weekly
  total. Keep the note that `workdays` is guaranteed non-empty by the serializer.
- Update the `--- capacity proration ---` comment block above `_is_workday`: the D4 history
  (hours no longer landing on zero-capacity days) still holds and must be preserved; only
  the description of what the stored number means changes.
- `spread_estimate`, `distribute_cents`, `period_key`, `enumerate_periods` and every
  cents-reconciliation path are **untouched**. Estimate spreading has never depended on
  capacity and must not start now.

### 1.5 — `serializers.py`

- `WorkloadSettingsSerializer.Meta.fields`: `"max_weekly_hours"` → `"max_daily_hours"`.
- `validate_max_weekly_hours` → `validate_max_daily_hours`; error strings say
  `max_daily_hours must be a number >= 0` / `... must be <= {MAX_HOURS}`.
- Keep the `quantize_hours()` call — the daily cap must quantize through the same cents
  rounding as everything else so stored values reconcile exactly.
- `validate_workdays` and `validate_week_start_day` are unchanged.

### 1.6 — `views.py` and `service.py`

- `views.py`: import `DEFAULT_MAX_DAILY_HOURS`; `settings_get`'s no-row default payload emits
  `"max_daily_hours": DEFAULT_MAX_DAILY_HOURS`. Keep the read-never-writes behaviour.
- `service.py`: import `DEFAULT_MAX_DAILY_HOURS`; `_resolve_work_settings` returns
  `(max_daily_hours, workdays, week_start_day)`; update its docstring and the local variable
  at the `compute_workload` call site and at the `capacity_for_period(...)` call.
- Neither file's control flow changes — this is a rename plus one default value.

### 1.7 — Tests

`tests/test_aggregation_pure.py` (no DB, runs standalone):

- Update the existing capacity cases to the daily basis.
- **Add the regression test that is this phase's real bar** — assert the new call with
  `max_daily_hours=8.0` produces exactly the numbers the old call produced with
  `max_weekly_hours=40.0`, for Mon-Fri workdays, across all three granularities and at
  least one month with 21 workdays and one with 23:

  ```
  day  , workday      -> 8.0        day , Sat/Sun -> 0.0
  week                -> 40.0
  month 2026-08 (21)  -> 168.0
  month 2026-09 (22)  -> 176.0
  ```

  Compute the expected month values from a hand-verified workday count, not from the
  function under test.

- Keep the existing empty/degenerate-workdays coverage. If a test named for the old field
  exists (`..._max_weekly_hours`), rename it rather than deleting it.

`tests/test_work_settings.py`:

- Rename every payload key and assertion (`40.0` → `8.0`, `40.13` → the daily equivalent for
  the quantization test, `32.5`/`25.0`/`20.0` custom-value cases keep their numbers — they
  test validation, not semantics).
- `test_..._over_cap_rejected` still uses `10001`; `test_..._negative` still uses `-1`.
- The response-keys assertion must now expect `{"max_daily_hours", "workdays", "week_start_day"}`.
- Add one test asserting a PUT carrying the OLD key `max_daily_hours`-less body is rejected —
  i.e. `{"max_weekly_hours": 8.0, "workdays": [...], "week_start_day": 1}` returns 400,
  proving D2's "no alias" is actually enforced and not merely unimplemented.

`tests/test_workload_db.py`:

- The helper signature `..., max_weekly_hours=40.0, workdays=None, week_start_day=1)` becomes
  `max_daily_hours=8.0`; update the two inline comments that reason about the derived day cap
  (`# day cap = 8.0h, well above the 4h logged` is now the value itself, not a derivation;
  `max_weekly_hours=5.0  # day cap = 1.0h` becomes `max_daily_hours=1.0`).
- The wrong-workspace isolation case keeps its intent; only the field name and value change.

---

## Success criteria

Run from `apps/api/` (see the `backend-test-db-isolation` notes for interpreter/Postgres setup):

1. `python manage.py makemigrations --check --dry-run` — clean, no pending migrations.
2. `python manage.py check` — clean.
3. `python -c "import plane.workload.constants"` — the module-load assertions still pass.
4. `pytest plane/workload/tests/ -q` — zero failures.
5. `grep -rn "max_weekly_hours\|DEFAULT_MAX_WEEKLY_HOURS" apps/api/plane/workload/ --include=*.py`
   returns hits ONLY inside `migrations/0003_*.py` and `migrations/0004_*.py` (frozen history).
6. The regression test in 1.7 passes — proving the default-config output is byte-identical
   to the pre-change behaviour.

## Commit

`feat(workload): configure the hour cap per day (default 8h) instead of per week`

---

## Step 1.8 — `month_buckets`: calendar-month hours (added 2026-08-22, plan D6)

Added after the rename was already in progress, on the user's validation request that a month
must be measured 1st-to-last-day rather than first-week-to-last-week. **Land this as its own
commit, after the rename commit** — it is a separate concern and a separate reviewable change.

### The defect it fixes

At month zoom the chart requests `granularity=week`, and the badge attributes a week bucket to
the month containing the week's START. Verified against real dates (Mon-Fri, week starts Monday):

```
bucket 2026-08-03  ->  Aug 3..Aug 7    ok
bucket 2026-08-10  ->  Aug 10..Aug 14  ok
bucket 2026-08-17  ->  Aug 17..Aug 21  ok
bucket 2026-08-24  ->  Aug 24..Aug 28  ok
bucket 2026-08-31  ->  Aug 31..Sep 4   LEAKS 4 workdays into August, and removes
                                       them from September's own total
```

Up to ~32h misattributed against a 168h denominator, in both directions depending on the month.
The client cannot repair it: at week granularity it holds only week-summed hours.

**Quarter focus is already exact** — its buckets are whole months, and a month bucket cannot
straddle a quarter boundary. Do not "fix" it.

### The change — `aggregation.py`

`spread_estimate` already iterates `target_days` and calls `period_key(d, granularity,
week_start_day)` per day. Accumulate a second dict in the SAME loop, keyed by calendar month:

- Reuse `period_key(d, "month", week_start_day)` for the key. Do NOT hand-format `f"{d.year}-
{d.month:02d}"` — the month key format must have exactly one definition, and `period_key`
  already owns it (`week_start_day` is ignored for `month`, which is why passing it is safe).
- Clip identically to `buckets`: only days satisfying `win_from <= d <= win_to` are counted.
  The two maps must agree on which days exist, or the badge and the columns describe different
  windows.
- Return `(buckets, month_buckets, unscheduled_cents, dirty)` — a 4-tuple. There is exactly one
  production call site (`service.py`) plus the pure tests, so widening the tuple is cheaper and
  more honest than a flag argument or a second traversal.
- Update the docstring's Returns block and add `month_buckets` to the semantics list.

### The change — `service.py`

- Unpack the new element at the `spread_estimate(...)` call.
- Accumulate per-row `month_buckets` the same way `sparse` is accumulated, in cents, converting
  with `from_cents` at the response boundary so it reconciles exactly like `buckets`.
- Emit `"month_buckets": <dict>` on every row, next to `"buckets"`. Sparse — a month with no
  hours is simply absent; do NOT pad it with zeros against `periods`, because `month_buckets` is
  deliberately independent of the requested granularity.
- `_empty_response` needs no change (it emits no rows).
- Do NOT touch `capacity_buckets`, `over`, `total`, `total_capacity` or `periods`. This adds a
  field; it changes no existing one.

### Tests

`tests/test_aggregation_pure.py`:

- Update every existing `spread_estimate` unpack to the 4-tuple.
- Add the straddle test, which is the whole point: one issue spanning `2026-08-31 .. 2026-09-04`
  at `granularity="week"` must produce a single `buckets` entry keyed `2026-08-31`, and
  `month_buckets` split across `2026-08` (Aug 31 only) and `2026-09` (Sep 1-4). Assert the two
  maps sum to the same total — the split must lose no cents.
- Add a test that `month_buckets` respects the `[win_from, win_to]` clip.

`tests/test_workload_db.py`:

- Assert `month_buckets` is present on a row and carries the calendar-month total for a
  boundary-spanning issue.

### Success criteria for 1.8

- `python -m pytest plane/workload -q` green.
- The straddle test fails if `month_buckets` is replaced by a copy of `buckets` — verify by
  making it fail once on purpose before accepting it.
- `buckets`, `capacity_buckets`, `periods` and every total are byte-identical to before 1.8 for
  the same request.

## Commit for 1.8

`feat(workload): report calendar-month hours so the badge is exact at month zoom`
