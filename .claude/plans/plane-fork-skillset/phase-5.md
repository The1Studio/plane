# Phase 5 — `plane-propagate` Skill

**Effort:** S · **Blocked by:** Phase 4 · **Blocks:** Phase 6
**Family:** downstream propagation. **One HARD-GATE** (before opening sibling-repo issues).
Implements the CLAUDE.md STANDING RULE: every new feature must update downstream surfaces.
Cite `rules/kit-pr-workflow-boundary.md` + the standing rule. **Never edits sibling repos** from this PR.

## Files owned (NEW)

| File                                                 | Purpose                                                                                                |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `skills/plane-propagate/SKILL.md`                    | Skillmark body: detect new endpoints/fields → draft sibling-repo issues → HARD-GATE → background open. |
| `skills/plane-propagate/references/sibling-repos.md` | The sibling-repo matrix + which surface each change type needs.                                        |

## Sibling-repo matrix (from CLAUDE.md §Sibling repos + standing rule)

| Repo                           | Propagate when                                                              | Issue content       |
| ------------------------------ | --------------------------------------------------------------------------- | ------------------- |
| `plane-mcp-server`             | new endpoint that is NOT a generic Issue field → needs an explicit MCP tool | new tool spec       |
| `plane-node-sdk`               | any new endpoint/field                                                      | TS binding          |
| `plane-python-sdk`             | any new endpoint/field                                                      | Python binding      |
| `plane-claude-plugin`          | new user-facing feature                                                     | plugin/skill update |
| `docs` / `developer-docs`      | new feature/endpoint                                                        | doc page            |
| `plane-deploy` / `helm-charts` | ONLY if new env var / service                                               | deploy var          |

## Decision tree (SKILL.md)

```
1. Source of changes:
     - read .claude/plane-propagation-queue.md (written by plane-scaffold-feature), OR
     - diff a feature branch: new urls.py paths + new serializer fields since base.
2. Classify each change → which sibling surfaces it touches (matrix above).
     Generic Issue field? → SDKs + docs only (no explicit MCP tool).
     New non-generic endpoint? → + plane-mcp-server explicit tool.
     New env var/service? → + deploy/helm.
3. Draft one issue body per affected sibling repo (title + body + the source endpoint/field).
4. ⛔ HARD-GATE: AskUserQuestion before opening ANY external issue. Show the full list
     (repo → title) for review. Open only on confirmation.
5. On confirm: spawn a BACKGROUND sub-agent per issue using /t1k:issue against the sibling repo.
     Report each resulting URL, one line each. STOP. Do NOT babysit/merge (kit-pr-workflow-boundary).
6. Mark the propagation-queue entries done.
```

## HARD-GATE (cite `rules/workflow-gates.md`)

### `<HARD-GATE>` — Before opening sibling-repo issues (override: explicit user confirm)

The skill MUST NOT open any issue on a sibling repo without `AskUserQuestion` confirmation showing the
exact repo+title list. Per `kit-pr-workflow-boundary` + the CLAUDE.md standing rule: open issues from a
**background** sub-agent, report the URL, and STOP — never edit a sibling repo from this repo's PR, never
offer to babysit/merge the sibling issue.

## Activation

Trigger phrases: "propagate this feature", "update downstream repos", "open MCP/SDK issues for the new
endpoint", "downstream propagation", "after-feature propagation".

## Steps

1. Author `sibling-repos.md` (the matrix above, sourced from CLAUDE.md).
2. Author `SKILL.md` with the decision tree + the `<HARD-GATE>` block + the background-only open rule.

## Verify checks

```bash
# Dry-run: feed a sample propagation-queue entry (new endpoint), confirm the skill drafts the
# correct sibling set per the matrix WITHOUT opening anything (gate not yet confirmed).
cat .claude/plane-propagation-queue.md      # sample input exists
# Assert: a generic-Issue-field change drafts SDKs+docs only (no MCP tool);
#         a new non-generic endpoint additionally drafts a plane-mcp-server tool.
```

## Success criteria

- For a sample new endpoint, the skill drafts correct issues for plane-mcp-server + both SDKs + docs.
- The HARD-GATE blocks any open until confirmed; opens run as background sub-agents and report URLs only.
- No code path edits a sibling repo or this repo's PR with sibling changes.

## Risk Assessment

| Risk                                                                       | Likelihood (1-5) | Impact (1-5) | Score | Mitigation                                                                                       |
| -------------------------------------------------------------------------- | ---------------- | ------------ | ----- | ------------------------------------------------------------------------------------------------ |
| Edits a sibling repo from this repo's PR (rule violation)                  | 2                | 4            | 8     | HARD-GATE + kit-pr-workflow-boundary: background issue-open only, report URL, stop.              |
| Opens issues without confirmation (noise on sibling repos)                 | 2                | 3            | 6     | Mandatory AskUserQuestion gate before any open.                                                  |
| Misses a required surface (e.g. forgets MCP tool for non-generic endpoint) | 3                | 3            | 9     | Matrix-driven classification; "non-generic endpoint → MCP tool" rule explicit per standing rule. |

## Timeline

| Item             | Effort |
| ---------------- | ------ |
| sibling-repos.md | S      |
| SKILL.md body    | S      |
| **Phase total**  | **S**  |
