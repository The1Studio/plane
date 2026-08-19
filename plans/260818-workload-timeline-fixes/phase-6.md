# Phase 6 — Downstream propagation

**Goal:** satisfy `CLAUDE.md`'s standing rule — a response-shape change is not done until the
sibling repos carry it. Depends on Phase 1. Parent: [`plan.md`](plan.md).

## What changed in the contract

`GET /api/workload/workspaces/<slug>/` (and the `/api/v1/` mirror in `api_views.py`, if it exposes
the same serializer):

| Field                              | Change                                                           |
| ---------------------------------- | ---------------------------------------------------------------- |
| `periods[]`                        | now spans the whole requested window, not just populated buckets |
| `rows[].capacity_buckets` / `over` | consequently gain an entry per window period                     |
| `rows[].weekly_buckets`            | **new** — `{week_start_date: hours}`, granularity-independent    |
| `rows[].weekly_capacity`           | **new** — the workspace weekly max, float                        |
| `rows[].tasks[].project_id`        | **new** — required to link a task to its work item               |

`total` / `total_over` / `buckets` are unchanged in meaning; `total_over` is now computed against a
window-complete capacity, so its **value** can change for existing callers even though its
definition did not. Call that out in the propagation issues — it is the one silent behavioural
change.

## Targets

Per `.claude/skills/plane-propagate/references/sibling-repos.md`, and opened as issues/PRs **in
those repos** — never edited from this repo's PR:

1. `plane-mcp-server` — the `get_workload` tool's result schema and description.
2. `plane-node-sdk` — workload response bindings.
3. `plane-python-sdk` — same.
4. `plane-claude-plugin` / `docs` / `developer-docs` — only if they document the workload response
   shape; check before opening.

## How

Use the `plane-propagate` skill. One issue per target repo, each carrying the table above and a link
to this plan's Phase 1.

## Success criteria

- An issue or PR exists in every applicable sibling repo, linked from this repo's PR body.
- The `CLAUDE.md` "Custom features" `workload/` entry names the new fields.
- No sibling repo was edited from this repo's branch.
