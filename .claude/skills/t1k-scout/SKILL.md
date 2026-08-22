---
name: t1k:scout
description: "Explore codebase with context-aware skill injection. Use for 'find where X is implemented', 'how is Y used', 'show all places that call Z' across source, skills, and docs."
keywords: [explore, search, find, codebase, navigate, usages, grep]
argument-hint: "[query]"
effort: low
tools: [Read, Glob, Grep, Bash, Task, Agent]
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Scout — Codebase Exploration

Context-aware codebase search using the `Explore` agent with skill context injection.

## Skill Activation
Read ALL kit-level `.claude/t1k-activation-*.json` files PLUS module-level fragments under `.claude/modules/<module>/` matching the same glob.
Match query keywords against ALL fragments. Activate all matching skills before exploring.

When resolving a `mappings[].skills[]` entry to a skill dir, accept BOTH the bare-slug form (`nakama-rpc`) and the full-prefixed form (`t1k-nakama-rpc`) — the CI prefixer self-heals legacy bare refs at release time but the SSOT in fragment files stays bare. Refs that don't resolve via either form are drift; surface to the user (consult `t1k-doctor` check #47).

## Module-Aware Search (if `installedModules` or `modules` present in metadata.json)

Follow protocol: `skills/t1k-modules/references/module-detection-protocol.md`

1. Read `.claude/metadata.json` → installed modules
2. Annotate each finding with its module: "Found in module: dots-core" or "Found in: kit-wide"
3. If searching for a pattern, prioritize skills from the relevant module
4. Include module ownership in result labels

## Default Search Paths

Read `.t1k-manifest.json` to determine installed kit paths, then search:

| Path | What it Contains |
|---|---|
| Source code root | Project implementation files |
| `.claude/skills/` | Encoded knowledge base |
| `docs/` | Technical documentation |

## Process

1. **Activate skills** — match query keywords via activation fragments
2. **Scope query** — map keywords to relevant source paths
3. **Run `Explore` agent** with scoped paths + query
4. **Annotate results** — label each finding as Source / Skill / Doc
5. **Reuse check** — if query is about implementing something, flag existing code first
6. **Scope any negative result** — report "zero across `<paths>`", never a bare "does not exist". Read-only/vendored/submodule code is in scope for discovery even when it is out of scope for editing. See `rules/negative-result-scope.md`.

## Cross-Repo Search (--cross-repo flag)

```
/t1k:scout --cross-repo <query>
```

**Requires:** `gh` CLI authenticated. Default scope is current project only.

1. Read `.claude/metadata.json` → `installedModules` → collect unique `repository` values
2. For each repo: `gh search code --repo {owner}/{repo} "{query}" --json path,repository,textMatches`
3. Results format per match:
   ```
   [{repo}] {file-path}
   > {match context — 3 lines around match}
   ```
4. Rank: exact match > partial match. Cap at 10 results per repo.
5. If `gh` unavailable: warn and fall back to local search only

## Agent

Uses `Explore` subagent — built-in, no registry delegation needed.

## Scope

Codebase exploration only — does NOT implement, modify, or plan.
