# Plane propagation queue

Entries written by `plane-scaffold-feature` / `plane-propagate`; processed entries carry a
`Propagated:` line with the opened issue URLs.

## workload-parent-rollup

- Feature: parent issues derive estimate hours, due date, and hours-weighted progress % from
  countable leaf descendants (read-only UI; PUT → 400 PARENT_HAS_CHILDREN; matrix leaf-only;
  bulk estimates omits parents).
- New endpoints: `GET /api/workspaces/<slug>/workload-rollups/?issue_ids=…` (+ `/api/v1/` mirror).
- Changed shapes: single estimate GET (`hours: null` + `is_parent` + `rollup` for parents);
  PUT 400 `{"error","error_code"}`; matrix + bulk estimates semantic shifts.
- Source commits: 94b5a3d14a (backend), 5812f185bd (frontend), 9205dc46e2 (plans).
- Propagated: 2026-07-03 · **All 6 implemented & merged 2026-07-04** (mcp-server#3, node-sdk#2, python-sdk#2, plane-claude-plugin#2, docs#2, developer-docs#2 — every issue auto-closed)
  - The1Studio/plane-mcp-server#2 — https://github.com/The1Studio/plane-mcp-server/issues/2
  - The1Studio/plane-node-sdk#1 — https://github.com/The1Studio/plane-node-sdk/issues/1
  - The1Studio/plane-python-sdk#1 — https://github.com/The1Studio/plane-python-sdk/issues/1
  - The1Studio/plane-claude-plugin#1 — https://github.com/The1Studio/plane-claude-plugin/issues/1
  - The1Studio/docs#1 — https://github.com/The1Studio/docs/issues/1
  - The1Studio/developer-docs#1 — https://github.com/The1Studio/developer-docs/issues/1

## project_ext — 2026-08-12

- Feature: project visibility (`Project.network`, 0 = secret/private, 2 = public) over the
  public API. The core `/api/v1/` project serializer
  (`plane.api.serializers.project.ProjectCreateSerializer.Meta.fields`) omits `network`, so DRF
  silently drops it on create AND update — a PATCH with `{"network": 0}` returns 200 OK with the
  project still public. Exposed from the fork-owned `project_ext` app rather than editing core.
- New endpoints:
  - `GET/PATCH /api/v1/workspaces/<slug>/projects/<project_id>/visibility/` — body `{"network": 0|2}`; GET any ws member, PATCH ws admin.
  - `PATCH /api/v1/workspaces/<slug>/project-visibility/` — body `{"project_ids": [...], "network": 0|2}`; ws admin; one unknown id fails the whole call (no partial update).
- New fields: none on core models — `project_ext` owns no tables (no migration).
- Related upstream bug (report separately, do NOT fix in core): `plane/api/views/project.py:234-238`
  passes the `project_lead` _User object_ into `ProjectMember.objects.create(member_id=...)`, which
  expects a UUID → ValidationError → generic `400 {"error": "Please provide valid detail"}` AFTER the
  project is already committed (no transaction). Caller sees 400, project exists, lead has no
  ProjectMember row. One-word fix: `project_lead_id`.
- Propagation needed: MCP tool in `plane-mcp-server` (DONE locally — `set_project_visibility`,
  `get_project_visibility`, `set_projects_visibility_bulk`), SDK bindings in `plane-node-sdk` +
  `plane-python-sdk`, docs update.

## cascade_ext module cascade + terminal-subtree pruning — 2026-08-28

- Feature: two things shipped together in the existing `cascade_ext` app
  (`plans/260828-module-cascade-terminal-status/`, Plane PLANE-189).
  1. **Module cascade** — a module moving to `completed`/`cancelled` cascades that terminal group
     onto every live module member PLUS each member's full descendant subtree, behind the same
     confirmation modal the per-issue cascade uses. Apply writes the module's own `status` and the
     issue states in ONE transaction. `MAX_MODULE_CASCADE_ITEMS = 100` is a **refusal, not a
     truncation**: over it, preview returns `over_cap: true` with an EMPTY `items` array and apply
     returns 400 having written nothing (module status included).
  2. **BEHAVIOR CHANGE to the shipped per-issue cascade** — a descendant already in a terminal group
     now PRUNES its entire subtree instead of being traversed through. A live sub-item under a
     cancelled parent is left live where it used to be swept. New rejection reason
     `under_terminal_ancestor` (the old `not_a_descendant` would be a false label for a live id
     behind a pruned branch).
- New endpoints:
  - `GET /api/cascade-ext/workspaces/<slug>/projects/<project_id>/modules/<module_id>/cascade-preview/?status=<completed|cancelled>`
    — note the query param is `status` (a MODULE status), **not** `group` as on the issue routes.
    Returns `{target_group, depth_capped, over_cap, cap, summary{total_live,eligible,ineligible,already_terminal}, items[]}`.
  - `POST /api/cascade-ext/workspaces/<slug>/projects/<project_id>/modules/<module_id>/cascade-apply/`
    — body `{status, item_ids}`; `item_ids` omitted/null = every eligible item, `[]` = none.
    Returns `{module, status, updated[], rejected[{id, reason}]}`. Archived module → 400.
- New fields: none on core models — no migration, no new app, no touch-point edit.
- Propagation needed:
  - `plane-mcp-server` — `preview_module_cascade` tool, `update_module(..., cascade=False)`
    mirroring `update_work_item`. TRAP: `update_module` coerces an unrecognized `status` to `None`
    (`plane_mcp/tools/modules.py:166-176`), so the cascade branch must key off the VALIDATED value,
    never the raw argument. ALSO: `plane_mcp/tools/cascade_ext.py`'s module docstring and
    `update_work_item`'s help still state the old "still traversed through" rule, which item 2 above
    made false — correct them in the same PR.
  - `plane-node-sdk` + `plane-python-sdk` — bindings for both routes.
  - `plane-claude-plugin` — user-facing "complete a module and everything in it", naming the
    100-item refusal.
  - `docs` + `developer-docs` — the `reason` enum, the 400 shapes, and the pruning behavior change.
  - `plane-deploy` / `helm-charts` — NOT applicable; no new env var, no new service. The cap is a
    hardcoded constant on purpose.
- Propagated: 2026-08-28
  - The1Studio/plane-mcp-server#39 — https://github.com/The1Studio/plane-mcp-server/issues/39
  - The1Studio/plane-node-sdk#11 — https://github.com/The1Studio/plane-node-sdk/issues/11
  - The1Studio/plane-python-sdk#11 — https://github.com/The1Studio/plane-python-sdk/issues/11
  - The1Studio/plane-claude-plugin#8 — https://github.com/The1Studio/plane-claude-plugin/issues/8
  - The1Studio/docs#8 — https://github.com/The1Studio/docs/issues/8
  - The1Studio/developer-docs#8 — https://github.com/The1Studio/developer-docs/issues/8
