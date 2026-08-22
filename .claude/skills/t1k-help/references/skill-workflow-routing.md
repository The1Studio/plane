---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
<!-- t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true -->

# Skill Workflow Routing (T1K Core)

Common multi-skill chains with preconditions, handoff, and exit criteria. Each chain is advisory — use as a starting point, not a rigid script.

## Chain 1: New Feature (plan → cook → test → review)

**Trigger:** User wants to add a new feature from scratch.

**Preconditions:** Task is clear. If not, run `/t1k:brainstorm` first.

**Steps:**
1. `/t1k:plan <task>` — produces `plans/{timestamp}-{slug}/` with phase files and tasks
2. `/t1k:cook <plan-path>` — executes the plan; internally chains scout → implement → test → review
3. `/t1k:git cm` — conventional commit as part of `/t1k:cook` finalization

**Exit:** Tests pass; review green; commit in git log.

## Chain 2: Bug Fix (debug → fix → test)

**Trigger:** User reports a runtime error, test failure, or unexpected behavior.

**Preconditions:** Error is reproducible or a log/stack trace is available.

**Steps:**
1. `/t1k:debug <issue>` — root-cause investigation; no code changes until cause confirmed
2. `/t1k:fix <plan-from-debug>` — applies the fix; auto-chains to `/t1k:test`
3. If fix fails: return to `/t1k:debug` with new findings

**Exit:** Tests green; root cause documented in commit message.

## Chain 3: Exploration (scout → brainstorm → plan)

**Trigger:** User wants to understand the codebase before committing to a design.

**Preconditions:** None.

**Steps:**
1. `/t1k:scout <query>` — parallel file discovery and context gathering
2. `/t1k:brainstorm <topic>` — generate alternatives with trade-off analysis
3. `/t1k:plan <chosen-option>` — formalize into phased plan

**Exit:** Plan directory created; user approves phases.

## Chain 4: Issue Backlog (triage → cook --auto)

**Trigger:** User wants to process a batch of GitHub issues or PRs.

**Preconditions:** `github` MCP connected; at least one kit repo has open issues.

**Steps:**
1. `/t1k:triage` — fetch, classify, and filter actionable issues across all kit repos
2. `/t1k:cook --auto` — run through the actionable list autonomously

**Exit:** Actioned issues closed or commented; remaining items reported.

## Chain 5: Session Wrap (watzup → handoff)

**Trigger:** End of session or handoff to another developer.

**Preconditions:** None.

**Steps:**
1. `/t1k:watzup` — session summary (commits, errors, in-progress tasks, telemetry)
2. `/t1k:handoff` — save session context to resumable state

**Exit:** Handoff file written; next session can resume via `/t1k:handoff load`.

## Chain 6: Release Pipeline (test → review → ship → babysit-pr)

**Trigger:** User wants to ship a completed feature to main.

**Preconditions:** Implementation complete; no failing tests.

**Steps:**
1. `/t1k:test` — full test suite; must be green before proceeding
2. `/t1k:review` — adversarial code review; address all critical findings
3. `/t1k:ship` — full release pipeline (conventional commit, tag, PR)
4. `/t1k:babysit-pr` — monitor CI and reviewers until merged

**Exit:** PR merged; tag created; changelog updated.

## Post-Implementation Checklist

After completing any implementation:
- `/t1k:review` — before merging
- `/t1k:ship` — full shipping pipeline
- `/t1k:watzup` — session summary

## Notes

- Chains can be interrupted and resumed — use `/t1k:handoff` between steps if needed
- `/t1k:cook` auto-chains internal steps (scout → implement → test → review) — no need to invoke manually
- Parallel work: use `/t1k:worktree` for isolated branches and `/t1k:team` for multi-agent orchestration
