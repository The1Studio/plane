---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# TheOneKit Command Chaining

## Common Chains

Each step starts only after the prior completes:

| Chain | Steps | Trigger |
|---|---|---|
| Plan then Implement | `/t1k:plan` → `/t1k:cook` | New feature request |
| Implement then Validate | `/t1k:cook` → `/t1k:test` → `/t1k:review` | After each phase |
| Debug cycle | `/t1k:debug` → `/t1k:fix` → `/t1k:test` | Runtime bug |
| Release gate | `/t1k:test` → `/t1k:review` → commit | Before merge |
| Triage cycle | `/t1k:triage` → `/t1k:cook --auto --parallel` | Issue/PR backlog |

## Auto-Chains (Run Without User Prompt)

- `/t1k:cook` always ends with `/t1k:test` (verify implementation)
- `/t1k:fix` always ends with `/t1k:test` (verify fix)
- **Any command that updates `.claude/skills/`** → spawn a **background sub-agent** for `/t1k:sync-back` (`Task` tool, `run_in_background: true`). NEVER manually copy files and NEVER run the skill inline. See `skills/t1k-fix/references/error-recovery.md` → "Background Sub-Agent Invocation".
- **Any command that discovers a skill bug** → spawn a **background sub-agent** for `/t1k:issue` (same pattern). NEVER manually create issues and NEVER run the skill inline.

## Require User Intervention

- Release/milestone gates (approval needed)
- `/t1k:git pr` (PR review needed)
- Major refactors (scope confirmation needed)

## Resume Interrupted Workflow

Call `TaskList`, find `in_progress` tasks, read `metadata.phaseFile` for context, continue from last completed step.

## Task Orchestration Pattern

`/t1k:plan` creates Claude Tasks — one per phase. `TaskCreate` fields:
- `title`: "Phase N: <name>"
- `metadata.phase`: N
- `metadata.planDir`: `plans/{timestamp}-{slug}/`
- `metadata.phaseFile`: `plans/{timestamp}-{slug}/phase-0N-*.md`
- `addBlockedBy`: list of predecessor task IDs (sequential phases)

`/t1k:cook` picks up existing tasks — never re-creates:
1. Call `TaskList` to find tasks with status `pending` or `in_progress`
2. Claim lowest-ID unblocked task first
3. CRITICAL: call `TaskUpdate(status="in_progress")` before writing any code
4. CRITICAL: call `TaskUpdate(status="completed")` before reporting done
