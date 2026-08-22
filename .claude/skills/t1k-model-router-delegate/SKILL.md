---
name: t1k:model-router:delegate
description: "Run any agent on a cheaper LLM. The PreToolUse:Task interceptor handles this automatically when modelMapping covers the agent's `model:` frontmatter; this skill is the explicit form for when you want to delegate without going through Task."
keywords: [delegate, cheap model, opencode, route, subagent, model-mapping, intercept, route to cheap, swap model, kimi, glm]
argument-hint: "<agent-name> \"<task>\" --provider <provider> --model <model>"
effort: low
version: 3.39.4
origin: theonekit-model-router
repository: The1Studio/theonekit-model-router
module: model-router
protected: false
---

## How v2 Works

The kit no longer ships shim agents. The delegation contract is:

```bash
bash .claude/scripts/mr-delegate.sh <agent-name> "<task>" --provider <provider> --model <model>
```

The script:
1. Discovers `.claude/agents/<agent-name>.md` (cwd → `CLAUDE_PROJECT_DIR` → `~/.claude/agents`).
2. Reads frontmatter for `permissionMode` / `maxTurns` / `maxBudgetUsd` (fallback: `plan` / 25 / $5).
3. Runs `claude -p --agent <name> --model <chosen-cheap-model>` against the chosen provider.
4. Returns the agent's text output.

**Primary call path is the Task interceptor** (`hooks/mr-task-interceptor.cjs`), not this skill. The flow:

```
main session → Task(subagent_type="t1k-unity-dots-core-implementer", prompt="...")
            ↓
   PreToolUse hook reads the agent's `model:` frontmatter
            ↓
   matches modelMapping["claude-sonnet-4-6"] → { opencode-go, deepseek-v4-flash }
   (opus-family keys never get here — they hit the kit passthrough floor first)
            ↓
   hook denies the Task, runs mr-delegate.sh, returns output as systemMessage
            ↓
main session sees the cheap result as if Task had succeeded
```

Engine-kit specialization is preserved: the Unity DOTS agent's full prompt + tools run, just on Kimi instead of Opus.

## When to Use the Explicit Form (this skill)

Most delegation happens automatically via the Task interceptor. Call `/t1k:model-router:delegate` explicitly only when:

- You're outside a Task spawn (e.g. running mechanical work from a Bash hook script).
- You want to force a specific (provider, model) that overrides `modelMapping`.
- You're debugging — explicit invocation surfaces the full mr-delegate.sh output.

```bash
# Force opencode-go/glm-5.2 for a heavy review, bypassing any modelMapping defaults
bash .claude/scripts/mr-delegate.sh t1k-code-reviewer \
  "audit src/auth/ for OWASP Top 10" \
  --provider opencode-go --model glm-5.2
```

## Model + Provider Selection

When you call the explicit form, YOU pick (provider, model). When the interceptor fires, the **mapping** picks for you.

1. Read `.claude/model-capabilities.md` for model strengths/costs.
2. Read `.claude/providers-config.json` for available providers.
3. Choose the best (provider, model) for task complexity.

Pass via `--provider <provider> --model <model>` flags. Both required — no defaults.

## Model Quick Reference

| Need | Model | Provider | Why |
|------|-------|----------|-----|
| Cheapest possible | `deepseek-v4-flash` | opencode-go | Only enabled budget tier; the shipped `modelMapping` default |
| Best balance | `kimi-for-coding` | kimi | Premium tier, the routed Kimi coding primary |
| Best reasoning | `glm-5.2` | opencode-go | Premium reasoning tier — what the reasoning sort picks |
| Long context (1M) | `minimax-m3` | opencode-go | Widest window in the catalog, and tool-capable |
| Mid-tier reasoning | `deepseek-v4-pro` | opencode-go | Reasoning without paying premium |
| Vision (image blocks) | `gpt-5.4-mini` | kimi | Head of the vision capability pipe |

Every model here is `enabled: true` in `.claude/providers-config.json`. Older names still seen in issues
and archived design docs — `qwen3.5-plus`, `kimi-k2.5`, `glm-5.1`, `minimax-m2.7`, the <!-- mr-models: allow-disabled -->
`mimo-*` family — ship **disabled** and are not valid `--model` targets unless a consumer
re-enables them locally.

Full details: read `.claude/model-capabilities.md`.

## Safety

Every delegation enforces:
- Tool whitelist from the agent's own frontmatter (Claude Code respects `tools:` / `disallowedTools:`).
- Permission mode read from agent frontmatter; safe fallback (`plan`) if missing.
- Max turns from agent frontmatter; default 25 if missing.
- Budget cap from agent frontmatter; default $5 if missing.
- Timeout (5 minutes default).
- No nested delegation (`MR_SPAWNED` guard at both the script and the interceptor).
- Write lock (single write-capable agent at a time when `mode=acceptEdits`).
- Telemetry (events sent to T1K cloud for monitoring).
- `excludeAgents` list in `t1k-config-mr.json` — any agent here is never intercepted (e.g. `t1k-architect`, `t1k-planner` for tasks that genuinely need Opus).

## Logs & Telemetry

- Local logs: `~/.model-router/calls.jsonl` (carries the agent name).
- Tool usage: `~/.model-router/tool-usage.jsonl`.
- Worker schema: the existing `role` column carries the agent name (no migration).

See `The1Studio/theonekit-model-router#42` for the v2 design rationale and `#54` for the v3.3.0 kit-enforced Opus-family passthrough policy.
