---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Routing Protocol

## Standard Routing (All Registry-Routed Commands)

1. **Read resolved config:** Check for `.t1k-resolved-config.json` first (CLI-generated, pre-merged)
   - If exists: read `routing.roles.<role>` for pre-resolved agent name (older configs may use `routing.<role>` — accept either)
   - If absent: fall back to manual resolution below

2. **Manual resolution (fallback):**
   - Read ALL `.claude/t1k-routing-*.json` files
   - Sort by `priority` field (descending — higher number wins)
   - For each role, use the highest-priority registration found
   - Fallback to `t1k-routing-core.json` (p10) if role not found elsewhere

3. **If no registry files exist:** Use `AskUserQuestion` to ask user which agent to use

4. **Pre-Task interception check (modules):** Before invoking the resolved agent via Task, scan `.claude/rules/*.md` (and `~/.claude/rules/*.md`) for any module rule whose activation gate passes AND whose body intercepts spawns for this role (e.g. `mr-transparent-routing.md` triggers when `modelRouter.enabled=true` + `mode="transparent"` and intercepts `implementer`/`reviewer`/`tester`/`docs-manager` → mr-delegate.sh). If intercepted, follow the rule's alternative invocation (typically a Bash call) instead of Task. If not intercepted, proceed with Task using the resolved agent name.

## Module-First Routing

In the module-first architecture, **modules are independently installed units** with their own versions. Routing considers which modules are installed (from `metadata.json` → `installedModules`).

**Mode 1 — Single-Module Task** (keywords match 0-1 installed modules):
- Standard highest-priority routing. One agent per role.
- Inject that module's skills into the agent prompt.

**Mode 2 — Multi-Module Task** (keywords match 2+ installed modules):
- Context-based routing. Each module's agent handles its own domain.
- Triggers multi-agent pipeline (parallel domain agents).
- Example: "combat UI" → dots-combat-implementer for logic + ui-developer for UI.

## Module Routing Overlays

Module routing overlays (from `module.json` → `routingOverlay` or CI-generated fragments):
- Module agents: p91+ (deeper dependency = higher priority, computed: `91 + dependency_depth`)
- Kit-wide agents: p90
- Core fallback: p10

## Commands Using This Protocol

| Command | Role(s) |
|---------|---------|
| `/t1k:cook` | `implementer`, `t1k-planner`, `t1k-project-manager`, `t1k-docs-manager`, `t1k-git-manager` |
| `/t1k:fix` | `implementer`, `t1k-debugger` |
| `/t1k:debug` | `t1k-debugger` |
| `/t1k:test` | `t1k-tester` |
| `/t1k:review` | `reviewer` |
| `/t1k:triage` | `reviewer`, `t1k-skills-manager` |
| `/t1k:plan` | `t1k-planner` |
| `/t1k:brainstorm` | `t1k-brainstormer` |
| `/t1k:docs` | `t1k-docs-manager` |
| `/t1k:git` | `t1k-git-manager` |
| `/t1k:modules` | `t1k-skills-manager` |
