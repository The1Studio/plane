# Phase 1 — Backend: `WorkloadSettings` model + API

**Goal:** a workspace-scoped settings row and its dual (app + public) API surface, serving the
contract pinned in [`phase-0.md`](phase-0.md). Depends on Phase 0. Runs concurrently with Phase 2.

Parent plan: [`plan.md`](plan.md).

## Ownership

`apps/api/plane/workload/` — `models.py`, `serializers.py`, `views.py`, `api_views.py`,
`urls.py`, `api_urls.py`, `migrations/`.

Does **not** touch `aggregation.py` (Phase 2) or `service.py` (Phase 3).

## Model

New table in the `workload` app — **no column on any core model** (`docs/FORK.md` DB rule).

```python
class WorkloadSettings(models.Model):
    """Workspace-wide work configuration: max weekly hours, workdays, week start.

    Replaces the per-member WorkloadCapacity grain (deleted in Phase 3). One row
    per workspace; a workspace with no row reads the constants.py defaults.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField("db.Workspace", on_delete=models.CASCADE,
                                     related_name="workload_settings")
    max_weekly_hours = models.FloatField(
        default=DEFAULT_MAX_WEEKLY_HOURS,
        validators=[MinValueValidator(0), MaxValueValidator(MAX_HOURS)])
    workdays = ArrayField(models.PositiveSmallIntegerField(), default=default_workdays)
    week_start_day = models.PositiveSmallIntegerField(default=DEFAULT_WEEK_START_DAY)
    created_by / created_at / updated_at   # mirror WorkloadEstimate
```

Constraints:

- `week_start_day` between 0 and 6 (`CheckConstraint`).
- `workdays` non-empty — enforced in the serializer (min length 1) **and** as a
  `CheckConstraint(Q(workdays__len__gt=0))` backstop. An empty array is the divide-by-zero
  described in the plan's risk table.
- `default=default_workdays` must be a **module-level callable**, not a mutable list literal —
  a shared list default is a Django footgun and `makemigrations` will serialise it wrong.

## Serializer

`WorkloadSettingsSerializer` validating:

- `max_weekly_hours` — `0 <= x <= MAX_HOURS`; quantised with `quantize_hours()` so it reconciles
  with the cents arithmetic in `aggregation.py`.
- `workdays` — list of ints, each `0..6`, unique, non-empty; normalised to ascending order on write.
- `week_start_day` — int `0..6`.

## Views

Shared handlers in `views.py` (the `capacity_list`/`capacity_put` pattern at
`views.py:179-235` is the template), reused by `api_views.py` for the public API — same
two-surface split the workload app already uses.

| Route | Methods | Permission |
|---|---|---|
| `/api/workspaces/<slug>/work-settings/` | GET, PUT | GET `ADMIN,MEMBER` · PUT `ADMIN` |
| `/api/v1/workspaces/<slug>/work-settings/` | GET, PUT | same |

GET returns the defaults for a workspace with no row (never 404). PUT is `update_or_create`.

There is **no DELETE** — a workspace always has effective settings.

## Data seed

`get_or_create` on read is *not* used (it would write on a GET). The row is created lazily by the
first PUT; reads fall back to defaults in the handler.

## Tasks

1. `constants.py` import wiring; move `MAX_HOURS` re-export so `models.py` no longer reaches into
   `aggregation.py` for it (`models.py:17` currently does).
2. Model + migration. Run `makemigrations --check --dry-run` after.
3. Serializer + validation tests.
4. Views + URL entries in both `urls.py` and `api_urls.py`.
5. Tests: GET default fallback, PUT round-trip, PUT as MEMBER → 403, empty `workdays` → 400,
   `week_start_day=7` → 400, `max_weekly_hours=-1` → 400.

## Success criteria

- `python manage.py check` clean.
- `python manage.py makemigrations --check --dry-run` reports no pending migrations.
- Workload pytest suite green, including the six new validation tests above.
- **The new app's tests are visible to CI** — the pytest job takes a hardcoded fork-app list, so
  confirm `workload` is present in `.github/workflows/company-main-ci.yml` before assuming green CI
  means anything.
