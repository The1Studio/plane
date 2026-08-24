# Phase 1 — File propagation issues in the sibling repos

Done **before** any implementation, per decision D7 ("propagate everywhere, file issues first, cook after").

## Classification

This change adds no endpoint and no field. It changes the **behavior of two existing generic `Issue` fields** (`assignees`, `target_date`) on the existing create endpoints. Under `.claude/skills/plane-propagate/references/sibling-repos.md` § "Classification Rule" that is the *generic Issue field* tier — no new MCP tool. The MCP server still needs an issue, because `create_work_item`'s documented behavior changes: a caller who omits `assignees` or `target_date` now gets values back that it did not send.

## Ownership

Files touched in THIS repo: none. Sibling repos are never edited from this repo's PR (`.claude/rules/plane-fork-discipline.md`, `rules/kit-pr-workflow-boundary.md`) — file issues only, then stop.

## Issues to file

| Repo | Issue content |
|---|---|
| `The1Studio/plane-mcp-server` | `create_work_item` docstring: omitting `assignees` now assigns the creator (project `default_assignee` takes precedence); omitting `target_date` now sets today in the caller's user timezone. Passing `[]` / `null` explicitly still means nobody / no due date. Intake creation is unaffected. |
| `The1Studio/plane-node-sdk` | Same behavior note on the issue-create binding; document that an omitted field is no longer equivalent to an explicit empty value. |
| `The1Studio/plane-python-sdk` | Same, Python binding. |
| `The1Studio/plane-claude-plugin` | User-facing: work items created through the plugin arrive assigned and dated by default. |
| `The1Studio/docs` | User-facing page describing the defaults and how to opt out (clear the chip / pill before saving). |
| `The1Studio/developer-docs` | API reference note on the absent-vs-empty distinction, the precedence order, and the `max(today, start_date)` rule. |

Not filed: `plane-deploy`, `helm-charts` — no new env var and no new service.

## Success criteria

- Six issues open, each linking back to the PR branch name for this plan.
- Each issue states the absent-vs-explicit-empty distinction verbatim; that is the part an SDK consumer will get wrong.
- No commits pushed to any sibling repo.
