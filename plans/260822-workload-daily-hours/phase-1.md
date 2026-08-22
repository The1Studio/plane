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

| granularity | new expression |
|---|---|
| `day` | `round(float(max_daily_hours), 2)` on a workday, else `0.0` |
| `week` | `round(max_daily_hours * len(workdays), 2)` |
| `month` | `round(max_daily_hours * _workdays_in_month(year, month, workdays), 2)` |

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
