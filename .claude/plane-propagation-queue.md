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
- Propagated: 2026-07-03
  - The1Studio/plane-mcp-server#2 — https://github.com/The1Studio/plane-mcp-server/issues/2
  - The1Studio/plane-node-sdk#1 — https://github.com/The1Studio/plane-node-sdk/issues/1
  - The1Studio/plane-python-sdk#1 — https://github.com/The1Studio/plane-python-sdk/issues/1
  - The1Studio/plane-claude-plugin#1 — https://github.com/The1Studio/plane-claude-plugin/issues/1
  - The1Studio/docs#1 — https://github.com/The1Studio/docs/issues/1
  - The1Studio/developer-docs#1 — https://github.com/The1Studio/developer-docs/issues/1
