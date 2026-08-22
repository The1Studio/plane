---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# TheOneKit Session Lifecycle

## Start of Session

### TIER 1 — Native (always loaded, survives /clear)
1. Read `CLAUDE.md` — confirm project context, installed kits, constraints
2. `$HOME/.claude/rules/*.md` loaded automatically — includes kit conventions
3. **Check feature flags (MANDATORY):**
   - Read ALL `t1k-config-*.json` files for `features.*` flags
   - If `features.mcp` is true: verify MCP connection per kit-specific instructions

### TIER 2 — SessionStart Hook (survives /clear, re-fires)
4. `generate-baseline-context.cjs` runs automatically (registered in settings.json)
   - Reads `$HOME/.claude/metadata.json` (SSOT) for installed modules, versions, kit info
   - Falls back to `.t1k-module-summary.txt` (CLI-generated) if no metadata
   - Also reads `t1k-modules.json` to show available (uninstalled) modules
   - Output: `[t1k:context] Kit: <name> v<version> | Modules (<N>): <list>`
   - AI now knows module context from SSOT without extra file dependencies

### Global-Only Mode

When AI sees `[t1k:global-only]` in hook output:
1. Note that T1K is running from global install (core skills available)
2. Suggest once: "This project doesn't have T1K installed locally. Run `t1k init` for project-level config."
3. Do NOT repeat the suggestion in the same session
4. Proceed normally — global T1K provides skills, agents, rules, and hooks
5. Module-specific features (installed modules, per-project activation) are not available in global-only mode

### TIER 3 — T1K Activation (partial /clear survival)
5. **Activate baseline skills:**
   - Read ALL `t1k-activation-*.json` → collect entries with `"sessionBaseline": true`
   - sessionBaseline skills are in REQUIRED modules only
   - Activate all baseline skills

### MODULE STATE CHECK
6. **Check module state:**
   Follow protocol: `skills/t1k-modules/references/module-detection-protocol.md`
   - If v3: read `installedModules` → per-module versions, verify deps satisfied
   - If v2 (legacy): read `modules` list → suggest `/t1k:doctor fix` to migrate to v3
   - If `kits` key (init format): kits installed but modules not individually tracked → read `t1k-modules.json` for available modules
   - If flat/core-only: skip module checks
   - If file manifest missing but module in metadata: warn user, suggest reinstall
   - **ALWAYS read `t1k-modules.json`** to know ALL available modules (installed + not-yet-installed). Proactively suggest relevant uninstalled modules when user's topic matches their keywords.

### PLAN/TASK RESUME
7. Check `plans/` for active plan directory (most recent timestamp)
8. Call `TaskList` — identify any `in_progress` tasks to resume

## Prompt Cycle (UserPromptSubmit)

On EVERY user prompt, BEFORE AI processes it:
1. `check-module-keywords.cjs` fires (registered in settings.json as UserPromptSubmit hook)
   - Reads `$HOME/.claude/metadata.json` (SSOT) → installed modules
   - Reads `t1k-modules-keywords-*.json` → keyword-to-module map (CI-generated, preferred)
   - Falls back to `t1k-modules.json` activation mappings (source-repo fallback)
   - If prompt matches keyword for UNINSTALLED module → warn (max 3, dedupe by module)
   - Output: `[t1k:module-suggest] keyword="ECS" module="dots-core" action="t1k modules add dots-core"`
   - If all matched modules installed → no output (silent)

Then AI processes prompt:
2. **Module Auto-Suggestion** — if hook output contains `[t1k:module-suggest]`:
   a. Parse all suggestions (keyword, module, action fields)
   b. Batch into single offer: "Your request involves '{keyword}' which requires '{module}' (not installed). Want me to install it?"
   c. If multiple: "I see {N} uninstalled modules needed: {list}. Want me to install them?"
   d. If user agrees → run action(s) via Bash → verify success → resume original task
   e. If user declines → proceed with available context, note what may be missing
   f. Do NOT ask repeatedly for the same module within a session
3. Classify command (cook/fix/debug/etc.)
4. **Routing — follow `skills/t1k-cook/references/routing-protocol.md`**
5. **Skill Activation — follow `skills/t1k-cook/references/activation-protocol.md`**
6. **Module Context — follow `skills/t1k-cook/references/subagent-injection-protocol.md`** (if spawning agents)
7. Execute command with module-aware agent

## During Work

- Use T1K commands exclusively for routing
- Track every task with `TaskUpdate` (start + finish)
- After each code change: check compilation/run output for errors
- After any error fixed: update relevant `$HOME/.claude/skills/` gotcha entry
- **When modifying module files**: note which module the file belongs to (from metadata)
- **When suggesting skills**: only suggest skills from installed modules
- **After any skill file updated**: ALWAYS invoke `/t1k:sync-back` as a **background sub-agent** (`Task` tool with `run_in_background: true`). NEVER run inline — it interrupts the user's current task. See `skills/t1k-fix/references/error-recovery.md` → "Background Sub-Agent Invocation" for the spawn pattern.
- **After discovering a skill/agent bug**: ALWAYS invoke `/t1k:issue` as a **background sub-agent** (same pattern). NEVER manually create issues and NEVER run the skill inline.

### Self-Validation Rule (MANDATORY)

AI MUST verify its own work before asking user to test:
1. After ANY fix/update/implementation: check compile/run output → confirm zero errors
2. After ANY implementation (not just test fixes): run the FULL test suite → confirm zero failures BEFORE reporting done
3. After ANY file deletion or rename: grep all source files for references first, update them, THEN delete
4. After ANY skill update: read the skill file back → verify content is correct
5. NEVER say "please test this" or report "done" until you have confirmed ALL tests pass
6. Test count must match pre-change count (no tests silently lost due to compilation errors hiding them)

## Finalize Phase / Feature

1. Registry `t1k-tester`: run test suite, confirm zero failures
2. Registry `reviewer`: code review (includes module boundary checks)
3. Registry `t1k-docs-manager`: sync `docs/` if affected
4. **Module integrity check**: run `/t1k:doctor` module checks (verify installed module versions and deps)
5. **Sync-back check**: if any `$HOME/.claude/skills/` files modified, spawn a **background sub-agent** to run `/t1k:sync-back` (see `skills/t1k-fix/references/error-recovery.md` → "Background Sub-Agent Invocation"). NEVER manually copy files and NEVER run the skill inline.
6. Registry `t1k-git-manager`: `/t1k:git cm` with conventional commit message

## Wrap Session

- Run `/t1k:watzup`: `git log --oneline -10` + error/log check + module summary
- Confirm all in-progress tasks are marked `completed`
- **Module integrity gate**: `/t1k:doctor` module checks pass?
- **Sync-back audit**: `git diff --name-only HEAD~10 | grep '$HOME/.claude/skills/'` — if any changed and not synced, spawn a background sub-agent for `/t1k:sync-back` now (never inline)
- Note any blocked tasks and their blockers
