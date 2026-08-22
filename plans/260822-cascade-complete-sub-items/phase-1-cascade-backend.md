# Phase 1 — `cascade_ext` backend: preview + apply

**Plane:** PLANE-110 · **Effort:** M (4h) · **Blocks:** Phases 2, 3
**Issue:** [The1Studio/plane#54](https://github.com/The1Studio/plane/issues/54)

## Goal

Two endpoints on a new fork app: one that answers *"what would cascade?"* and one that applies a
caller-selected subset atomically. **No core view is edited** — the default "only change this item"
path is the existing plain PATCH, untouched.

## Ownership

```
apps/api/plane/cascade_ext/**                             # NEW app
apps/api/plane/urls.py                                    # touch-point 2, one urlpatterns entry
apps/api/plane/settings/common.py                         # touch-point 1, INSTALLED_APPS
.claude/skills/_shared/references/fork-convention.md      # forkApps array
```

Scaffold with the `plane-scaffold-feature` skill — it handles `apps.py`, both touch-point
registrations and the `forkApps` entry in one pass. An app missing from `forkApps` is misclassified
by `plane-classify-path.cjs` **and** silently untested by `company-main-ci.yml`.

No `models.py` content, no migration beyond the empty package: this feature stores nothing.

## Endpoint contract (fix this first — Phase 2 codes against it)

**Preview** — `GET /api/cascade-ext/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/cascade-preview/?group=<completed|cancelled>`

```json
{
  "target_group": "completed",
  "depth_capped": false,
  "descendants": [
    { "id": "<uuid>", "identifier": "PLANE-42", "name": "…", "depth": 1,
      "project_id": "<uuid>", "project_name": "Plane",
      "state_id": "<uuid>", "state_name": "In Progress", "state_group": "started",
      "target_state_id": "<uuid>",
      "eligible": true, "reason": null }
  ]
}
```

`reason` ∈ `null | "no_matching_state" | "no_permission"`. Ineligible rows are **included** with
`eligible: false` — Decision 8 requires showing them disabled with a reason, not hiding them.
Already-terminal descendants are **excluded entirely** (Decision 5) but still traversed through.

`identifier` is `project.identifier + "-" + issue.sequence_id`. Build it server-side; the client
should not have to join projects to render a label.

**Apply** — `POST …/issues/<issue_id>/cascade-apply/`

```json
{ "state_id": "<uuid of the parent's new state>", "child_ids": ["<uuid>", "…"] }
// child_ids omitted or null  ⇒  every currently-eligible descendant (Decision 14).
// The UI always sends an explicit list; a headless caller (MCP) omits it.
```

Response `{ "parent": "<uuid>", "updated": [...], "rejected": [{"id": "…", "reason": "…"}] }`.

## Implementation

`service.py`:

```python
def resolve_target_group(state) -> str | None       # "completed" / "cancelled" / None
def collect_descendants(*, root_issue, target_group, actor_id) -> list[dict]
def apply_cascade(*, root_issue, state, child_ids, actor_id, slug, origin) -> dict
```

`collect_descendants` — level-order BFS, shared by both endpoints so preview and apply can never
disagree:

1. `visited = {root.id}`, `frontier = [root.id]`, `depth = 0`.
2. Per level: `Issue.issue_objects.filter(parent_id__in=frontier).exclude(id__in=visited)
   .select_related("state", "project").only(...)`. Use `issue_objects`, not `objects`, so
   soft-deleted and triage rows stay out.
3. A child whose `state.group` is terminal (**either** group, regardless of `target_group`) is
   excluded from the result but **still pushed to `frontier`** — a terminal node must not hide its
   own live descendants.
4. Stop at `MAX_DEPTH`; set `depth_capped: true` and log the root id. This plus `visited` is the
   cycle guard.
5. Resolve one target state per project:
   `State.objects.filter(project_id=pid, group=target_group).order_by("sequence").first()`.
   `sequence` is the ordering field (`db/models/state.py:84`). **`State.default` is not usable** —
   it marks the project's default *entry* state, normally unstarted. None found → `eligible: false`,
   `reason: "no_matching_state"`.
6. One membership query for all projects touched:
   `ProjectMember.objects.filter(member_id=actor_id, is_active=True, project_id__in=pids)
   .values_list("project_id", flat=True)`. Not a member → `eligible: false`,
   `reason: "no_permission"`.

`apply_cascade` — **re-runs `collect_descendants`**; when `child_ids` is omitted or `null` it accepts every eligible row (Decision 14), otherwise it **intersects** with the posted list. Anything posted
that is not currently eligible is dropped into `rejected` with its reason. This is the risk-15
mitigation: the posted list is a *request*, never an authorization. A client could otherwise name
any UUID and move it.

Then, inside a single `transaction.atomic()`:

- update the parent's state (this endpoint owns the parent write — the client must **not** also
  PATCH, or the parent moves outside the transaction);
- `bulk_update` the accepted children per project, batch 100. `bulk_update` skips `save()`, so set
  `updated_at` explicitly on each instance first;
- dispatch per child, mirroring `app/views/issue/base.py:674` — `issue_activity.delay(...)` and
  `model_activity.delay(...)` with the **pre-update** `state_id` as `current_instance`, built before
  the bulk write and dispatched after.

**`notification=False` on every cascaded child** (Decision 10) — load-bearing, not a typo. The
parent's own change notifies; #54 names a 20-child cascade firing 20 watcher notifications as a
defect. Activity entries are still written, so the audit trail is intact. This is the one place the
dispatch deliberately differs from the shape the core view uses.

## Tests — `apps/api/plane/cascade_ext/tests/`

| Case | Assert |
| --- | --- |
| 3-level tree, target `completed` | every live descendant listed at the right `depth`, each with its project's completed state |
| same tree, target `cancelled` | resolves to each project's cancelled state |
| `resolve_target_group` | unstarted→completed ⇒ `"completed"`; completed→completed ⇒ `None`; completed→started ⇒ `None`; completed→cancelled ⇒ `"cancelled"` |
| cancelled child, target `completed` | excluded from `descendants`; **its own live children still listed** |
| completed child, target `cancelled` | same, mirrored |
| cross-project child | `target_state_id` is that project's state, not the parent's |
| project with no state in the target group | `eligible: false`, `reason: "no_matching_state"` |
| actor not an active member | `eligible: false`, `reason: "no_permission"` |
| renamed states (`Done` → `Shipped`) | still resolved — proves group-not-name |
| `parent` cycle built directly via ORM | terminates, no `RecursionError` |
| leaf | `descendants: []` |
| **apply posts an ineligible id** | that id lands in `rejected`, is **not** moved, and the rest still apply |
| **apply posts a child that is not a descendant at all** | rejected, not moved |
| apply with `child_ids` omitted | every eligible descendant moves; ineligible ones still rejected with a reason |
| apply with `child_ids: []` | nothing cascades; only the parent moves (an explicit empty list is not "all") |
| apply raises mid-way (mock a failure) | parent's state is rolled back too — assert the parent's state is unchanged |
| notification suppression | every cascaded `issue_activity.delay` carries `notification=False` — assert the **kwarg**, not the call count |

## Success criteria

- [ ] `pytest apps/api/plane/cascade_ext/` green.
- [ ] `makemigrations --check --dry-run` reports no changes.
- [ ] `manage.py check` clean.
- [ ] `"cascade_ext"` in the `forkApps` array **and** the prose app list above it (the doctor's drift
      check enforces both).
- [ ] `git diff` touches **no** file under `apps/api/plane/app/` or `apps/api/plane/api/`.
- [ ] Preview and apply share one `collect_descendants` — grep proves no second traversal exists.
