# Propagation drafts — Views multi-layout switcher (`views_ext`)

**Status: UNFILED.** These are drafted issue bodies only. Per `.claude/rules/plane-fork-discipline.md`
§ "Feature propagation" + `rules/kit-pr-workflow-boundary.md`, opening an issue on a sibling repo is
an outward-facing action requiring explicit user approval — none has been given yet. Do not run
`gh issue create` against any of these until the user confirms. When approved, use the
`plane-propagate` skill (it knows the repo set, the HARD-GATE confirmation step, and the
background-sub-agent-per-issue pattern) rather than filing these by hand.

Source endpoint (contract SSOT: `plans/260817-1616-views-layout-switcher/plan.md` § "Contract"):

```
GET /api/views-ext/workspaces/<str:slug>/issues/
```

Classification (per `.claude/skills/plane-propagate/references/sibling-repos.md`): this is a
**new non-generic endpoint** on a fork-owned view (not a generic `Issue` field) → all three SDK/MCP
surfaces below apply.

---

## 1. `The1Studio/plane-mcp-server`

**Title:** `[views_ext] Add MCP tool for grouped workspace-view issue queries`

**Body:**

```
New backend endpoint: GET /api/views-ext/workspaces/<slug>/issues/ (views_ext Django app,
The1Studio/plane commit range ae36b3c721..dd9dd8852b, PR: <fill in on file>).

Request params:
  group_by      string|absent  state__group | priority | project_id | labels__id
  sub_group_by  string|absent  same set (Board sub-grouping; absent = single swimlane)
  before/after  YYYY-MM-DD     target_date range filter
  cursor        string         <page_size>:<page>:<offset>, standard Plane cursor pagination
  + the existing workspace-issues param set (assignees, priority, labels, state, etc. via
    ComplexFilterBackend/IssueFilterSet)

Response shape (byte-identical to WorkspaceUserProfileIssuesEndpoint):
  {
    "grouped_by": "priority" | null,
    "sub_grouped_by": string | null,
    "results": { "<group_key>": TIssue[], ... } | TIssue[]   // grouped vs ungrouped
    "total_count": number,
    "next_cursor": string, "prev_cursor": string,
    "next_page_results": bool, "prev_page_results": bool,
    "total_pages": number, "count": number, "extra_stats": null
  }

Requested tool: something like list_workspace_view_issues(workspace_slug, group_by?,
sub_group_by?, before?, after?, ...filters) wrapping this endpoint, mirroring whatever
convention the existing workspace-issues / profile-issues tools already use in this server.

Auth: WorkspaceViewerPermission — same auth class as other workspace-scoped read endpoints.

group_by/sub_group_by are server field paths (not UI labels); an invalid value returns
HTTP 400, never a silent flat fallback.
```

---

## 2. `The1Studio/plane-node-sdk`

**Title:** `[views_ext] Add TypeScript binding for GET /api/views-ext/workspaces/<slug>/issues/`

**Body:**

```
New endpoint: GET /api/views-ext/workspaces/<slug>/issues/

Add a typed client method (e.g. workspaceViews.listGroupedIssues(slug, params)) plus request/
response types matching the shape below. Casing is snake_case throughout, matching every other
Plane endpoint — do not camelCase at the wire layer.

Request params: group_by?, sub_group_by? (values: "state__group" | "priority" | "project_id" |
"labels__id"), before?, after? (YYYY-MM-DD), cursor?, plus the standard workspace-issues filter
params already bound elsewhere in this SDK.

Response type: grouped_by: string | null; sub_grouped_by: string | null; results: TIssue[] |
Record<string, TIssue[]>; total_count, next_cursor, prev_cursor, next_page_results,
prev_page_results, total_pages, count: number/bool as typed elsewhere in this SDK; extra_stats:
null.

400 on an invalid group_by/sub_group_by value — surface as a typed error, not a silent empty
result.

Full contract: plans/260817-1616-views-layout-switcher/plan.md § "Contract — pinned before any
parallel work" in The1Studio/plane.
```

---

## 3. `The1Studio/plane-python-sdk`

**Title:** `[views_ext] Add Python binding for GET /api/views-ext/workspaces/<slug>/issues/`

**Body:**

```
Same endpoint and shape as the Node SDK issue (The1Studio/plane-node-sdk, same title). Add the
equivalent typed client method + request/response models in this SDK's existing style (e.g.
matching how workspace-issues / profile-issues are already bound here).

GET /api/views-ext/workspaces/<slug>/issues/
Params: group_by?, sub_group_by? ("state__group" | "priority" | "project_id" | "labels__id"),
before?/after? (YYYY-MM-DD), cursor?, + standard workspace-issues filters.
Response: grouped_by, sub_grouped_by, results (list or dict-of-lists), total_count, next_cursor,
prev_cursor, next_page_results, prev_page_results, total_pages, count, extra_stats.

Full contract: plans/260817-1616-views-layout-switcher/plan.md § "Contract" in The1Studio/plane.
```

---

## Not proposed

- **`plane-claude-plugin`** — no new user-facing Claude-invokable capability; this is a UI-layer
  layout switcher consuming an existing MCP/SDK-shaped read endpoint. Skip per the sibling matrix
  ("only touched for features that expose a new Claude-usable capability").
- **`plane-deploy` / `helm-charts`** — no new env var or service introduced. Skip per the matrix.
- **`docs` / `developer-docs`** — plausible candidates (user-facing: "switch layouts on the Views
  tab"; developer-facing: the new endpoint). Left out of the drafted list above because the phase
  file's § 4 names only `plane-mcp-server` / `plane-node-sdk` / `plane-python-sdk` explicitly;
  flag to the user at the approval gate whether `docs`/`developer-docs` should be added too.
