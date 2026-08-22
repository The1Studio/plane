---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Environment Variables — .env Resolution Hierarchy

T1K resolves env vars in priority order (highest first). The implementation is
`.claude/scripts/resolve_env.py` — the single resolver; this table mirrors it.

| Tier | Location | Scope |
|------|----------|-------|
| 1 — Runtime | `process.env` (shell export) | Session only |
| 2 — Project skill-local | `.claude/skills/{name}/.env` | Single skill, this project |
| 3 — Project shared | `.claude/skills/.env` | All skills in project |
| 4 — Project global | `.claude/.env` | This project |
| 5 — User skill-local | `~/.claude/skills/{name}/.env` | Single skill, all projects |
| 6 — User shared | `~/.claude/skills/.env` | All skills, all projects |
| 7 — User global | `~/.claude/.env` | All projects on machine |

Tiers 2 and 5 are only consulted when a skill name is supplied
(`resolve_env('VAR', skill='t1k-extended-multimodal')`).

## Rules

- Never hardcode values — use env vars
- Document required vars in `.env.example` (no real values, committed to repo)
- Ensure `.env` is in `.gitignore`

## Anti-Rationalization Guards (Cook)

| Trap | Reality |
|------|---------|
| "This is too simple to plan" | Simple tasks hide complexity. Plan takes 30 seconds. |
| "I already know how to do this" | Knowing != planning. Write it down. |
| "The user wants speed" | Plan -> implement -> done is faster than implement -> debug -> rewrite. |
| "Let me just start coding" | Undisciplined action wastes tokens. Plan first. |
| "I'll plan as I go" | That's not planning, that's hoping. |
| "Just this once" | Every skip is "just this once." No exceptions. |

## Execution Trace

After task completes, if `features.executionTrace` enabled (default: true in `t1k-config-*.json`), output compact summary (max 15 lines):
- Modules matched, routing mode (single/multi-module)
- Agents used (role: agent-name, module, priority)
- Skills activated (count + top 5)
- Fallbacks used, warnings
