# Phase 3 — Wire into the app serializer; exclude intake

Depends on phase 2. Covers the web app, drafts, sub-work-items and epics — everything that reaches `IssueCreateSerializer`.

## Ownership

Edited (fenced core-edit exceptions):

- `apps/api/plane/app/serializers/issue.py` — `IssueCreateSerializer.validate` and `.create`
- `apps/api/plane/app/views/intake/base.py` — two serializer contexts (lines ~253, ~407)

Created:

- `apps/api/plane/issue_defaults_ext/tests/test_app_serializer.py`

Every edit carries `# The1Studio fork (work-item creation defaults)` per the convention already used in `apps/web/core/components/issues/issue-modal/base.tsx`.

## Edit 1 — `validate()`, target date

At the **end** of `validate`, after the existing `start_date > target_date` check, not before it. Placing it earlier would run the defaulted value back through a check it is constructed never to fail, and would change which error a genuinely-invalid payload reports.

```python
# The1Studio fork (work-item creation defaults) — an absent target_date
# becomes today (or start_date, if that is later). An explicit null is a
# deliberate "no due date" and is left alone. Update never defaults.
resolved = resolve_creation_target_date(
    is_create=self.instance is None,
    initial_data=self.initial_data,
    context=self.context,
    start_date=attrs.get("start_date"),
    user=get_current_user(),
)
if resolved is not None:
    attrs["target_date"] = resolved
```

`get_current_user` is `crum.get_current_user` — the same thread-local `plane/db/models/base.py:29` already uses to populate `created_by`. The serializer is constructed without a `request` in its context (`app/views/issue/base.py:395`), so there is no `self.context["request"]` to read; do not add one, that widens the core diff for nothing.

## Edit 2 — `create()`, assignee

Replace the existing `else:` branch (the project-default block, `issue.py:229-251`) with a call that absorbs it. The helper reproduces that block's member check verbatim, so behavior for a project WITH a default assignee is unchanged.

```python
else:
    # The1Studio fork (work-item creation defaults) — project default first,
    # then the creator. Only an absent assignee_ids reaches the creator
    # fallback; an explicit [] stays unassigned.
    resolved_assignee_id = resolve_creation_assignee_id(
        initial_data=self.initial_data,
        context=self.context,
        project_id=project_id,
        default_assignee_id=default_assignee_id,
        created_by_id=created_by_id,
        assignee_field="assignee_ids",
    )
    if resolved_assignee_id is not None:
        try:
            IssueAssignee.objects.create(
                assignee_id=resolved_assignee_id,
                issue=issue,
                project_id=project_id,
                workspace_id=workspace_id,
                created_by_id=created_by_id,
                updated_by_id=updated_by_id,
            )
        except IntegrityError:
            pass
```

`created_by_id` is already in scope — `issue.py:208` reads it off the freshly created row, populated by `BaseModel.save`. No new query and no `request` needed.

## Edit 3 — intake exclusion (D6)

`apps/api/plane/app/views/intake/base.py` builds its own context dicts at ~253 and ~407. Append one key to each:

```python
"apply_creation_defaults": False,  # The1Studio fork (work-item creation defaults)
```

The helper reads it via `context.get("apply_creation_defaults", True)`, so no other call site changes. Intake items are submitted by people who are frequently not project members; assigning them to the submitter would be wrong, and dating them would misrepresent a triage queue.

Do **not** touch `apps/api/plane/app/views/workspace/draft.py:215` — drafts are in scope per D6 and inherit the default when promoted.

## Tests

`tests/test_app_serializer.py`, through the serializer with a real project:

- create with no `assignee_ids` and no `target_date` → creator assigned, due today
- create with `assignee_ids: []` → unassigned; with `target_date: null` → no due date
- create with an explicit assignee → that assignee, creator not added
- project with `default_assignee` → default assignee wins over creator
- **update path:** `IssueCreateSerializer(issue, data={"target_date": None}, partial=True)` → target date stays null, no assignee added. Blocks the score-20 risk.
- update with neither field present → both untouched
- intake context (`apply_creation_defaults=False`) → neither default applied
- creator not a project member → unassigned, no exception
- future `start_date`, absent `target_date` → saves, `target_date == start_date`, no `ValidationError`

## Success criteria

- All tests pass; the pre-existing issue suite stays green.
- Core diff in `app/serializers/issue.py` is one added block in `validate` and one replaced block in `create` — nothing else.
- `python manage.py check` clean.
