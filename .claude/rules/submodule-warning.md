---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Git Submodule — Always Run From Parent Root

**MANDATORY:** Never launch Claude Code from inside a git submodule directory.

## Why

- **settings.json does NOT inherit** from parent projects. Hooks using relative paths (`node .claude/hooks/...`) resolve against CWD — if CWD is inside the submodule, those files don't exist → `MODULE_NOT_FOUND` errors.
- **MCP servers** are configured in the parent's `.claude/settings.json` — lost when running from submodule.
- **Skills and agents** live in the parent's `.claude/` — inaccessible from submodule CWD.
- **CLAUDE.md DOES walk up** the directory tree, but that's the ONLY thing that inherits. Hooks, MCP, and skills do not.

## Rule

| Scenario | Where to run Claude |
|----------|-------------------|
| Editing submodule files within parent project | **Parent project root** |
| Submodule as standalone project (has own `.claude/settings.json`) | Submodule root |
| Any doubt | **Parent project root** |

Edit submodule files using relative paths (e.g., `Packages/my-lib/...`). For git operations on the submodule, use `cd <submodule-path> && git ...` in Bash commands.

## Detection

If you see `MODULE_NOT_FOUND` errors for `.claude/hooks/` files during session start, the session was likely launched from inside a submodule. Exit and relaunch from the parent project root.
