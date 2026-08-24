# Phase 4 — Wire into the public API serializer

Depends on phase 2. Parallel with phase 3 — different files, no shared edit.

This is the path the MCP server, both SDKs and every API-key client use, so it is where the propagation issues from phase 1 come true.

## Ownership

Edited (fenced core-edit exceptions):

- `apps/api/plane/api/serializers/issue.py` — `IssueSerializer.validate` and `.create`

Created:

- `apps/api/plane/issue_defaults_ext/tests/test_api_serializer.py`

`apps/api/plane/api/views/issue.py` needs no edit: both construction sites (~436, ~668) already pass `default_assignee_id` in context and neither is excluded by D6.

## Edits

Structurally identical to phase 3, with two differences that will bite if copied blindly:

1. **The assignee field is `assignees`, not `assignee_ids`.** Pass `assignee_field="assignees"`. The absent-vs-empty check reads the payload by name, so the wrong name means the creator fallback silently never fires for API clients — and every test that only exercises the app serializer still passes.
2. The existing project-default block sits at `api/serializers/issue.py:194-206` and the surrounding `create` differs in shape from the app one. Read it before editing; do not assume the two files are copies of each other.

The `validate` insertion point is the same: after the existing `start_date > target_date` check.

## Tests

`tests/test_api_serializer.py`, mirroring phase 3's matrix against `IssueSerializer`:

- absent `assignees` → creator; `assignees: []` → unassigned
- absent `target_date` → today; explicit null → untouched
- project `default_assignee` wins
- update through `IssueSerializer(instance, partial=True)` → no defaults applied
- future `start_date` with absent `target_date` → equals `start_date`

Add one end-to-end API test hitting the real create endpoint with an API key and a body carrying only `name` — this is exactly the request an MCP `create_work_item` call with no optional args produces, and it is the one a docstring-only propagation issue cannot verify.

## Success criteria

- All tests pass; the existing public-API issue suite stays green.
- A `POST /api/v1/workspaces/<slug>/projects/<id>/issues/` carrying only `name` returns a work item with the creator assigned and today's `target_date`.
- The same POST with `"assignees": []` returns it unassigned.
