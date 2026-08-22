---
name: t1k:docs
description: "Create and update project documentation in docs/. Use for 'init docs', 'update docs after this change', 'generate a codebase summary', 'docs are out of date'."
keywords: [documentation, update docs, init docs, generate docs, summarize, readme]
argument-hint: "init|update|summarize"
effort: low
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Docs — Documentation Management

Manage project documentation in `docs/` directory.

## Operations
| Operation | Description |
|---|---|
| `init` | Create project-appropriate doc structure |
| `update` | Update docs after code changes |
| `summarize` | Quick codebase summary |

## Flags

Composable with any operation:

- `--advice` — before writing or updating any doc, spawn `t1k-kongming` for
  counsel on what to keep, cut, or restructure, and factor it into the change.
  It advises only; this skill stays responsible for every edit and still confirms
  writes with the user. Spawn it again when stuck, or before an irreversible docs
  change (deleting a doc, restructuring the tree). Full contract:
  `skills/t1k-cook/references/advisory-supervision.md`.

Docs-specific note: the highest-value checkpoint here is **before the first
write**, not after — counsel on what to cut is worth more than counsel on prose
already written. This skill's own scope rules still govern whether a doc should
be touched at all; `--advice` does not override them.

## Doc Structure
```
docs/
├── code-standards.md
├── system-architecture.md
├── project-changelog.md
├── development-roadmap.md
└── codebase-summary.md
```

## Agent Routing
Follow protocol: `skills/t1k-cook/references/routing-protocol.md`
This command uses role: `t1k-docs-manager`

## References
- `references/init-workflow.md`
- `references/update-workflow.md`
- `references/summarize-workflow.md`

