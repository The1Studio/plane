# Workload feature — downstream follow-ups (Phase 7)

The org's GitHub issue trackers are disabled, so the workload feature's
downstream propagation is tracked here instead. Source feature:
`feat/workload-time-estimates` (this repo).

## New API surface to expose

Now available on BOTH the app API (`/api/`, session auth) and the **public API
(`/api/v1/`, API-key auth)** — use `/api/v1/` for MCP/SDK/external clients.

- `GET|PUT|DELETE /api/v1/workspaces/{slug}/projects/{project_id}/issues/{issue_id}/workload-estimate/`
  — PUT body `{"hours": <number ≥0, ≤10000>}`; GET returns the estimate or `{"hours": null}`.
- `GET /api/v1/workspaces/{slug}/workload/?granularity=day|week|month&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD[&project_ids=csv&assignee_ids=csv&state_group=csv]`
- `GET /api/v1/workspaces/{slug}/projects/{project_id}/workload/?…same params`

Workload response: `{granularity, date_from, date_to, periods[], rows[{assignee_id, assignee_name, buckets{period:hours}, total}], unscheduled[{assignee_id, hours}], meta{…}}`.

> The estimate is a **separate endpoint**, not a field on Issue — generic issue
> create/update tools will NOT carry it; an explicit tool/binding is required.

## Tasks

- [x] `plane` backend — expose endpoints on the public API (`/api/v1/`, API-key auth). _(done)_
- [x] `plane-mcp-server` — tools `get_workload`, `get/set/delete_issue_workload_estimate`. _(done)_
- [ ] `plane-node-sdk` — add client bindings for the 3 endpoints.
- [ ] `plane-python-sdk` — add client bindings for the 3 endpoints.
- [ ] `developer-docs` / `docs` — document the endpoints + the workload tab.
- [ ] `plane-deploy` / `helm-charts` — no change expected (no new env/services).
