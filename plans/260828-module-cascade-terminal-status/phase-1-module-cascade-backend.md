# Phase 1 — `cascade_ext` backend: module preview + apply

**Effort:** M (4h) · **Depends on:** Phase 0 · **Blocks:** Phases 2, 3
**Plan:** `plans/260828-module-cascade-terminal-status/plan.md`
**Plane:** [PLANE-191](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/0cc383b3-e4fd-4a5d-a554-dca9a8323442)

## Goal

Two endpoints on the **existing** `cascade_ext` app that answer _"what would cascade if this module
went terminal?"_ and apply a caller-selected subset atomically with the module's own status write.
No new app, no new model, no migration, no core view edited, **no touch-point edit** — `cascade_ext`
is already in `INSTALLED_APPS`, already mounted at `apps/api/plane/urls.py:44`, and already in
`forkApps`.

## Ownership

```
apps/api/plane/cascade_ext/service.py                  # refactor + two new functions
apps/api/plane/cascade_ext/views.py                    # two new endpoint classes
apps/api/plane/cascade_ext/urls.py                     # two new paths
apps/api/plane/cascade_ext/tests/test_module_cascade.py  # NEW
```

Nothing outside `apps/api/plane/cascade_ext/`. If a diff touches anything else, stop — the design
went wrong.

## Endpoint contract (freeze this FIRST — Phase 2 codes against it, verbatim)

**Preview** — `GET /api/cascade-ext/workspaces/<slug>/projects/<project_id>/modules/<module_id>/cascade-preview/?status=<completed|cancelled>`

```json
{
  "target_group": "completed",
  "depth_capped": false,
  "over_cap": false,
  "cap": 100,
  "summary": {
    "total_live": 47,
    "eligible": 44,
    "ineligible": 3,
    "already_terminal": 12
  },
  "items": [
    {
      "id": "<uuid>",
      "identifier": "PLANE-42",
      "name": "…",
      "depth": 0,
      "is_module_member": true,
      "project_id": "<uuid>",
      "project_name": "Plane",
      "state_id": "<uuid>",
      "state_name": "In Progress",
      "state_group": "started",
      "target_state_id": "<uuid>",
      "eligible": true,
      "reason": null
    }
  ]
}
```

- The query parameter is `status` (a module status), **not** `group` — the per-issue endpoint's
  parameter is `group` and the two must not be confused. Valid values: `completed`, `cancelled`.
  Anything else → 400. `target_group` in the response is the resulting `State.group`, which for
  these two happens to be the same string; it is emitted separately so the client never has to
  assume the mapping.
- `depth: 0` means a direct module member; `depth: N` a descendant N levels below one.
  `is_module_member` is emitted explicitly rather than inferred from `depth == 0`, because a
  descendant may _also_ be a module member and the client groups the summary by membership.
- `reason` ∈ `null | "no_matching_state" | "no_permission"`.
- Ineligible rows are **included** with `eligible: false` (M10). Already-terminal work items are
  **excluded** from `items` and **prune their whole subtree** (M8, established for both subjects by
  Phase 0) — nothing beneath them is listed, walked, or changed. `summary.already_terminal` counts
  the terminal nodes actually encountered, not the items hidden behind them, which are never
  visited and therefore uncountable.
- `summary.total_live == len(items)` whenever `over_cap` is false. When `over_cap` is true,
  `items` is `[]` and `total_live` still reports the real number (M4) — the client renders the
  refusal from the summary alone.
- `identifier` is `project.identifier + "-" + issue.sequence_id`, built server-side.
- Archived module → **400** (M13), not 404.

**Apply** — `POST /api/cascade-ext/workspaces/<slug>/projects/<project_id>/modules/<module_id>/cascade-apply/`

```json
{ "status": "completed", "item_ids": ["<uuid>", "…"] }
```

- `item_ids` omitted or `null` ⇒ every currently-eligible item. An explicit `[]` ⇒ nothing
  cascades; only the module's status moves. (Mirrors Decision 14 — the UI always sends an explicit
  list, a headless MCP caller omits it.)
- Response: `{ "module": "<uuid>", "status": "completed", "updated": [...], "rejected": [{"id": "…", "reason": "…"}] }`
- `rejected[].reason` ∈ `"no_matching_state" | "no_permission" | "already_terminal" | "under_terminal_ancestor" | "not_in_module_tree" | "not_eligible"`. `under_terminal_ancestor` is Phase 0's reason, reused verbatim rather than re-derived.
- Over cap → **400** `{"error": "cascade exceeds MAX_MODULE_CASCADE_ITEMS", "total_live": 240, "cap": 100}`. Nothing is written, including the module's status — the caller falls back to a plain PATCH.
- Archived module → **400**.
- Permissions: preview `[ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST]` (same read gate as viewing the
  module); apply `[ROLE.ADMIN, ROLE.MEMBER]` (the roles that may write a module, matching
  `ModuleViewSet.partial_update`).

## Implementation

### 1. Refactor `collect_descendants` onto a seed set — without changing its contract

`service.py` currently walks from one `root_issue`. Extract the walk:

```python
def _collect_from_seeds(*, seed_ids, include_seeds, target_group, actor_id) -> dict:
    """Level-order BFS from a SET of seed issue ids.

    include_seeds=False -> seeds are the roots, excluded from the result
                           (the per-issue parent/sub-item case).
    include_seeds=True  -> seeds are themselves candidates at depth 0
                           (the module-member case).
    """
```

and keep the public signature intact:

```python
def collect_descendants(*, root_issue, target_group, actor_id) -> dict:
    return _collect_from_seeds(
        seed_ids={root_issue.id}, include_seeds=False,
        target_group=target_group, actor_id=actor_id,
    )
```

**This function's behavior is frozen as Phase 0 leaves it.** `tests/test_cascade_db.py` must pass
with **no assertion edited by this phase** — Phase 0's two inversions are already in the tree, and
this refactor must not touch a third. That is the acceptance gate for the refactor (risk-15 in the
plan). Keep its
returned key names (`descendants`, `depth_capped`, `traversed_ids`) exactly as they are; the module
path adapts on top rather than renaming them underneath the issue path.

Preserved verbatim from the existing implementation: `visited` set, `MAX_DEPTH = 20`,
`Issue.issue_objects` (never the default manager, so soft-deleted and triage rows stay out),
`select_related("state", "project")`, one query per level, one `State` query for all touched
projects keeping the lowest-`sequence` state per project, one `ProjectMember` query for all touched
projects, and — as of Phase 0 — **prune-at-terminal**: a terminal node is recorded in
`traversed_ids` and its children are never enqueued. Both subjects share that one rule; there is no
per-caller flag for it, deliberately, because a flag is how the two features drift back apart.

When `include_seeds=True`, seed rows are fetched with the same `Issue.issue_objects` +
`select_related` and enter the node list at `depth: 0`; `visited` is seeded with every seed id so a
`parent` cycle among members cannot loop.

### 2. `collect_module_cascade`

```python
MAX_MODULE_CASCADE_ITEMS = 100

MODULE_STATUS_TO_STATE_GROUP = {
    "completed": StateGroup.COMPLETED.value,
    "cancelled": StateGroup.CANCELLED.value,
}

def collect_module_cascade(*, module, target_group, actor_id) -> dict:
```

1. Seed ids — the canonical query, soft-delete-aware on **both** sides:

   ```python
   seed_ids = set(
       Issue.issue_objects.filter(
           issue_module__module_id=module.id,
           issue_module__deleted_at__isnull=True,
       ).values_list("id", flat=True)
   )
   ```

   `ModuleIssue` uses `related_name="issue_module"` on both FKs — from `Issue` the reverse accessor
   is `issue_module`. Do not reach for `module.issue_module.all()` and map to `.issue`; that
   bypasses `issue_objects` and lets soft-deleted and draft rows in.

2. `_collect_from_seeds(seed_ids=seed_ids, include_seeds=True, …)`.
3. Stamp `is_module_member = node["id"] in {str(i) for i in seed_ids}` on every row.
4. Build `summary`. `already_terminal` is the count of terminal nodes actually encountered
   (seeds included) — **not** a subtraction of `len(items)` from a traversal total, which under
   Phase 0's pruning would silently report zero for a branch nobody walked.
5. If `summary["total_live"] > MAX_MODULE_CASCADE_ITEMS`: set `over_cap=True`, replace `items` with
   `[]`, keep the summary. **Do not** truncate the list — a truncated list silently under-reports
   what a confirm would do, which is the failure mode the cap exists to avoid.

Empty module → `seed_ids` empty → return the zero-summary shape immediately; do not run the BFS.

### 3. `apply_module_cascade`

```python
def apply_module_cascade(*, module, status, item_ids, actor_id, slug, origin) -> dict:
```

1. `target_group = MODULE_STATUS_TO_STATE_GROUP[status]` (the caller has already validated
   `status`).
2. `collected = collect_module_cascade(...)`. If `over_cap` → raise a `CascadeCapExceeded` the view
   turns into the 400 above. **Raise before opening the transaction** so nothing, including the
   module's status, is written.
3. Re-derive `eligible_ids` from `collected` — `item_ids` is a request, never an authorization.
   `item_ids is None` ⇒ all eligible; `[]` ⇒ none. Everything requested-but-not-eligible lands in
   `rejected` with the reason from its node, `already_terminal` if it was traversed,
   `under_terminal_ancestor` if Phase 0's parent-chain check places it behind a pruned branch, or
   `not_in_module_tree` if it was never seen.
4. One `transaction.atomic()` block containing **both** writes (M5):
   - `module.status = status; module.updated_at = now; module.save(update_fields=["status", "updated_at"])`
   - the accepted issues, in 100-row `bulk_update(["state_id", "updated_at"])` batches. `bulk_update`
     skips `save()`, so `updated_at` is assigned explicitly — same as the issue path.
5. **After** the block commits, dispatch:
   - `model_activity.delay(model_name="module", model_id=str(module.id), requested_data={"status": status}, current_instance=json.dumps({"status": old_status}), actor_id=actor_id, slug=slug, origin=origin)` — this is the behavior the core viewset would have fired and which this endpoint bypasses (`app/views/module/base.py:708-716`).
   - per accepted item, `issue_activity.delay(type="issue.activity.updated", …, notification=False, origin=origin)` **and** `model_activity.delay(model_name="issue", …)`, exactly as `apply_cascade` does. `notification=False` is load-bearing (M11), not a typo.

   There is no module equivalent of `issue_activity` for a status change — `ACTIVITY_MAPPER` only
   carries `module.activity.created` / `module.activity.deleted`, both for `ModuleIssue` add/remove.
   `model_activity` is the whole module-side dispatch; do not invent a new mapper key.

### 4. Views

Two `BaseAPIView` subclasses in `views.py`, thin — every rule lives in `service.py` so preview and
apply cannot disagree:

- Validate `status` against `{"completed", "cancelled"}` → 400.
- `Module.objects.filter(pk=module_id, project_id=project_id, workspace__slug=slug).first()` → 404
  if absent.
- `if module.archived_at: 400` (M13).
- Apply additionally: `item_ids` must be a list, `null`, or omitted → else 400.
- `origin=base_host(request=request, is_app=True)`, as the issue endpoints do.

### 5. URLs

Two appended paths in the existing `urlpatterns`. Keep the `<uuid:module_id>` converter consistent
with the issue routes' `<uuid:issue_id>`.

## Tests — `apps/api/plane/cascade_ext/tests/test_module_cascade.py`

Follow `test_cascade_db.py`'s existing style and base class.

| #   | Case                                                       | Asserts                                                                                                               |
| --- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 1   | Empty module                                               | `summary.total_live == 0`, `items == []`, zero BFS queries                                                            |
| 2   | Flat module, mixed states                                  | only non-terminal members listed, `depth == 0`, `is_module_member` true                                               |
| 3   | Member with a 3-level subtree                              | every level listed, `depth` 0/1/2, `is_module_member` true only at 0                                                  |
| 4   | Member already `completed`, its child live                 | member excluded, `already_terminal == 1`, child **absent** — the member prunes its subtree (Phase 0)                  |
| 5   | Cancelling a module with a completed member                | completed member untouched (M8), live members get the _cancelled_ state                                               |
| 6   | Cross-project sub-item                                     | resolved to its own project's state in the group, not the module's project's                                          |
| 7   | Renamed target state (`Done` → `Shipped`)                  | still resolved by `group`, never by name                                                                              |
| 8   | Sub-item in a project the actor is not an active member of | listed, `eligible: false`, `reason == "no_permission"`                                                                |
| 9   | Project with no state in the target group                  | `reason == "no_matching_state"`                                                                                       |
| 10  | `parent` cycle among two module members                    | terminates, no duplicate rows                                                                                         |
| 11  | Apply with `item_ids=None`                                 | every eligible item moves                                                                                             |
| 12  | Apply with `item_ids=[]`                                   | **only** the module's status moves; zero issue writes                                                                 |
| 13  | Apply posting an ineligible id                             | that id lands in `rejected` with its reason; no write for it                                                          |
| 14  | Apply posting an id from a different module                | `rejected` with `not_in_module_tree`                                                                                  |
| 14b | Apply posting a live id beneath a terminal member          | `rejected` with `under_terminal_ancestor`; not written                                                                |
| 15  | Apply raises mid-`bulk_update` (patched)                   | module status **rolled back** — the atomicity gate for M5                                                             |
| 16  | 101 live items                                             | preview `over_cap: true`, `items == []`, `total_live == 101`; apply → 400 and **module status unchanged**             |
| 17  | Archived module                                            | preview and apply both 400                                                                                            |
| 18  | Non-terminal status (`in-progress`)                        | preview 400                                                                                                           |
| 19  | Activity dispatch                                          | one `model_activity` for the module; per item one `issue_activity` with `notification=False` and one `model_activity` |
| 20  | Query count on a 50-item module                            | one query per BFS level plus the fixed 2 (states, memberships) — asserts no N+1 crept in                              |
| 21  | **Regression**                                             | `test_cascade_db.py` passes unedited                                                                                  |

## Success criteria

- `pytest apps/api/plane/cascade_ext/tests/` green, including `test_cascade_db.py` with **zero**
  assertion edits.
- `python manage.py makemigrations --check --dry-run` reports no changes.
- `python manage.py check` clean.
- `git diff --name-only` touches only paths in § Ownership.
- The contract above is byte-identical to what Phase 2 codes against.
