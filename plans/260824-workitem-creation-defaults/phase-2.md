# Phase 2 — `issue_defaults_ext` fork app: helpers + unit tests

Every decision from `plan.md` lives here as a pure function. The serializers in phases 3–4 call in; they hold no logic of their own.

## Ownership

Created (fork-owned, no core edit):

- `apps/api/plane/issue_defaults_ext/__init__.py`
- `apps/api/plane/issue_defaults_ext/apps.py`
- `apps/api/plane/issue_defaults_ext/defaults.py`
- `apps/api/plane/issue_defaults_ext/tests/__init__.py`
- `apps/api/plane/issue_defaults_ext/tests/test_defaults.py`

Edited (touch-point 1, one appended line):

- `apps/api/plane/settings/common.py` — append `"plane.issue_defaults_ext"` to `INSTALLED_APPS`

Edited (fork infrastructure registry):

- `.claude/skills/_shared/references/fork-convention.md` — append `"issue_defaults_ext"` to the `forkApps` array

**No `migrations/` directory.** The app is model-less (read-only over core models), exactly like `workspace_ext`. `python manage.py makemigrations --check --dry-run` must stay clean.

**`forkApps` is load-bearing, not bookkeeping.** `.claude/scripts/plane-fork-test-paths.py` selects the CI test paths from that array — an app missing from it is both misclassified by the isolation audit AND silently untested. Add it in this phase, not later.

No `urls.py`: the app exposes no endpoint, so touch-point 2 is untouched.

## API

```python
# apps/api/plane/issue_defaults_ext/defaults.py

def local_today(user) -> date
```
`timezone.now()` converted into `user.user_timezone` (`"UTC"` when the user is `None` or the field is blank), then `.date()`. This is D8.

```python
def resolve_creation_target_date(*, is_create, initial_data, context, start_date, user) -> date | None
```
Returns the date to write, or `None` meaning "leave `target_date` exactly as the payload had it".

Returns `None` when any of: `is_create` is False · `context.get("apply_creation_defaults", True)` is False · `"target_date" in initial_data` (D2 — an explicit `null` is a deliberate no-due-date).
Otherwise returns `start_date` when `start_date` is set and later than `local_today(user)`, else `local_today(user)` (D5).

```python
def resolve_creation_assignee_id(*, initial_data, context, project_id, default_assignee_id, created_by_id, assignee_field) -> UUID | None
```
Returns the single assignee id to create, or `None` for "leave unassigned". `assignee_field` is `"assignee_ids"` for the app serializer and `"assignees"` for the public API one — the two payloads spell the field differently and a hardcoded name would silently no-op on one of them.

Order (D3):
1. `context.get("apply_creation_defaults", True)` is False → `None`.
2. `default_assignee_id` set **and** a valid project member (`ProjectMember`, `role__gte=15`, `is_active=True`, matching `project_id`) → return it. This clause is transcribed from the existing core check at `app/serializers/issue.py:232-240` so precedence is preserved byte-for-byte.
3. `assignee_field in initial_data` → `None` (D2 — an explicit `[]` means nobody). **This check sits BELOW clause 2 on purpose:** upstream already assigns the project default on an empty list, and D3 keeps existing project configuration authoritative. Only the new creator fallback is gated on absence.
4. `created_by_id` set and a valid project member by the same test → return it.
5. Otherwise `None`.

A member who was removed from the project, or downgraded below `role__gte=15`, fails clause 4 and the item is created unassigned rather than assigned to someone who cannot see it.

## Tests

`tests/test_defaults.py`, unit-level, no HTTP:

- absent `target_date` → today; explicit `None` → untouched; explicit date → untouched
- `is_create=False` → untouched, for both fields (**the score-20 risk**)
- `apply_creation_defaults=False` → untouched, for both fields
- future `start_date`, absent `target_date` → equals `start_date`, never today (D5)
- past `start_date`, absent `target_date` → today
- `user_timezone="Asia/Ho_Chi_Minh"` at `2026-08-24T23:30Z` → `2026-08-25`; the same instant at `"UTC"` → `2026-08-24` (D8)
- `user=None` → falls back to UTC without raising
- project default set + `assignee_ids` absent → project default (D3)
- project default set + `assignee_ids: []` → project default, matching upstream
- project default absent + `assignee_ids` absent → creator
- project default absent + `assignee_ids: []` → `None`
- project default set but not a project member + absent → creator
- creator not a project member → `None`
- `assignee_field="assignees"` behaves identically to `"assignee_ids"`
- `Issue.objects.create(...)` with no serializer leaves `target_date` null and creates no `IssueAssignee` — pins the bulk-import exclusion (D6) that costs no code

## Success criteria

- All unit tests pass.
- `python manage.py makemigrations --check --dry-run` clean.
- `python manage.py check` clean.
- `.claude/scripts/plane-fork-test-paths.py` lists the new app.
- `defaults.py` imports nothing from `plane.app` or `plane.api` — the dependency runs one way only.
