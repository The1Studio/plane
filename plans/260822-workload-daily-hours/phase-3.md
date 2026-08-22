# Phase 3 — Downstream propagation

**Plan:** [`plan.md`](plan.md).
**Depends on:** Phase 1 and Phase 2 both green and merged.
**Effort:** S (~1h)

Mandated by `CLAUDE.md`'s STANDING RULE and `.claude/rules/plane-fork-discipline.md`:
a change to an endpoint's shape is not done until the downstream surfaces are tracked.

---

## What changed downstream

A **breaking field rename** on a fork-owned, non-generic endpoint, on both surfaces:

- `GET`/`PUT` `/api/v1/workspaces/<slug>/work-settings/` — `max_weekly_hours` →
  `max_daily_hours`, default `40.0` → `8.0`. No alias; the old key is rejected (plan D2).
- `GET` `/api/v1/workspaces/<slug>/workload/` and the project variant — the response shape is
  unchanged, but `capacity_buckets` VALUES now derive from a daily cap. For a workspace left
  on defaults the numbers are identical; for one that had customised its weekly cap they
  change, because plan D1 resets stored values to `8.0`.

## Classification

Per `.claude/skills/plane-propagate/references/sibling-repos.md`, this is a
**non-generic endpoint on a fork-owned model** — not a generic Issue field.

| Repo | File an issue? | Content |
|---|---|---|
| `The1Studio/plane-mcp-server` | **NO** | Verified against the local clone: `grep -rln "work-settings\|work_settings\|max_weekly_hours" ~/Projects/plane-mcp-server/src` returns zero. No tool wraps this endpoint, so there is nothing to rename. **Re-run that grep before accepting this row** — it is a claim about the clone as of 2026-08-22, not a permanent fact. If a tool has since been added, file the issue. |
| `The1Studio/plane-node-sdk` | YES | Rename the binding's `max_weekly_hours` field to `max_daily_hours`; note the `40.0` → `8.0` default and that the old key now 400s. |
| `The1Studio/plane-python-sdk` | YES | Same rename, Python binding. |
| `The1Studio/plane-claude-plugin` | YES | User-facing: the workspace work-settings capability now configures a daily cap. |
| `The1Studio/docs` | YES | Update the work-settings page: field name, unit, new default, and the badge's new workday-exact capacity. |
| `The1Studio/developer-docs` | YES | API reference: renamed request/response field, breaking-change note, example payloads. |
| `The1Studio/plane-deploy`, `The1Studio/helm-charts` | **NO** | No new env var, no new service. |

## Steps

1. Run the `plane-propagate` skill. It owns the classification and the issue-filing flow —
   do not hand-roll `gh issue create`.
2. Before filing the mcp-server row's "NO", re-run the verification grep above against the
   local clone. Report what you actually ran and what it returned.
3. **Do not edit any sibling repo from this repo's PR** — issues only
   (`.claude/rules/plane-fork-discipline.md`, `rules/kit-pr-workflow-boundary.md`). Do not
   offer to babysit or merge the sibling issues/PRs from this session.
4. Update `CLAUDE.md`'s "Custom features (fork-owned)" `workload/` entry: it currently says
   "workspace-wide work settings (`WorkloadSettings`: max weekly hours, workdays, week
   start)". Change to the daily cap, and add that the timeline's capacity badge counts the
   focused period's workdays rather than summing per-bucket capacity.
5. Report every issue URL, one line each, then stop.

## Success criteria

- One issue per YES row above, each carrying the endpoint URL, the old and new field names,
  the default change, and the no-alias breaking-change note.
- The mcp-server "NO" backed by a freshly re-run grep, with its output quoted.
- `CLAUDE.md`'s workload entry reflects both changes.
- No commits pushed to any sibling repo.
