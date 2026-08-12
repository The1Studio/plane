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
