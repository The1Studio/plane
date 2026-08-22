---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# TheOneKit Execution Context

## Context Detection

**MANDATORY:** Read ALL `t1k-config-*.json` files to determine execution context.

Each config fragment declares what context it requires:

```json
{
  "kitName": "example-kit",
  "context": {
    "requiredPaths": ["src/", "package.json"],
    "requiredFeatures": ["mcp"],
    "description": "Requires project with src/ and package.json"
  }
}
```

If `requiredPaths` are present in the working directory → that kit's context is active.
If `requiredPaths` are absent → that kit's commands requiring those paths will fail.

## Core Layer (Always Available)

TheOneKit core commands run in ANY context:
- `/t1k:triage` always fetches from all registered repos regardless of context
- `/t1k:doctor`, `/t1k:help`, `/t1k:ask`, `/t1k:brainstorm`, `/t1k:plan` — context-independent
- `/t1k:scout`, `/t1k:watzup`, `/t1k:git` — require a git repository

## Kit-Specific Context

Kit-level configs register context-dependent commands:
- Commands requiring a specific runtime (e.g., a game editor, mobile SDK) will fail outside that context
- When a command fails due to missing context, report the missing requirement clearly
- Never silently skip — always explain what context is needed

## Detection Pattern

```
IF t1k-config-*.json has requiredPaths:
  FOR each required path:
    IF path does NOT exist in cwd → log: "command X requires {path} — not in context"
    Do NOT attempt kit-specific commands
ELSE:
  Context is available → proceed
```

## Fallback Behavior

- If no kit configs found: only core layer commands are available
- If kit context missing: report requirements, suggest switching to correct project directory
- Never attempt to fake context (e.g., creating dummy directories)
