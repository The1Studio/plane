---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# TheOneKit Error Recovery

## Registry-Based Error Routing

**MANDATORY:** Read ALL `t1k-routing-*.json` files.
Look up the `errorRecovery` map — match error type to role, then resolve role to agent.

| Error Type | Recovery Role | Command |
|------------|--------------|---------|
| Compilation error | `implementer` | `/t1k:fix` |
| Test failure | `t1k-tester` | `/t1k:fix --test` |
| Runtime error | `t1k-debugger` | `/t1k:debug` |
| Performance regression | `optimizer` | Kit-level command |
| Missing dependency | `implementer` | `/t1k:fix --quick` |

## Recovery Workflow

1. Match error type to role using `errorRecovery` map in routing registry
2. Resolve role to agent (highest-priority registry wins)
3. Dispatch to `/t1k:fix` or `/t1k:debug` as appropriate
4. After fix: always run `/t1k:test` to confirm resolution
5. Never suppress test failures to pass CI

## Stuck Detection (Auto-Escalation)

**After 3+ failed attempts** on the same error with `/t1k:fix` or `/t1k:debug`:

1. Auto-activate `/t1k:problem-solve` — classify the stuck-type and apply matching technique
2. If `mcp__sequential-thinking__sequentialthinking` MCP is available, use it for structured analysis
3. Identify which module owns the stuck task (module-scoped problem analysis)
4. Apply technique, then retry `/t1k:fix` with new approach
5. If still stuck after problem-solving: escalate to user with full analysis

## Error Classification

```
Simple:   single compile error, typo, missing import
Moderate: logic error, wrong API usage, missing config
Complex:  cascading failures, breaking API change, environment issue
```

## Self-Validation (MANDATORY)

AI must verify fixes work BEFORE asking user to test:
1. After any fix: check compilation/run output → confirm zero errors
2. After any test fix: run tests → confirm pass BEFORE reporting to user
3. After any skill update: read the skill file back → verify content is correct

## Skill Sync-Back After Fixes (MANDATORY)

**ALWAYS use the `/t1k:sync-back` and `/t1k:issue` SKILLS — NEVER manually copy files to kit repos or create issues by hand.** These skills handle routing, frontmatter preservation, module path mapping, and PR creation automatically.

### Background Sub-Agent Invocation (MANDATORY — NEVER INLINE)

Both `/t1k:sync-back` and `/t1k:issue` MUST be invoked via the `Task` tool with `subagent_type: "t1k-kit-developer"` (the registered specialist for kit-infrastructure work: skill/agent/rule edits, registry fragments, kit PR creation) and `run_in_background: true`. Fallback to `general-purpose` ONLY if `t1k-kit-developer` is not registered in this project's `.claude/agents/` (run `ToolSearch(query="select:Agent", max_results=1)` first to confirm `Agent` is callable, then check the routing registry). NEVER run them inline in the parent context — they would interrupt the user's current task with duplicate checks, diff reviews, and PR creation.

**Why `t1k-kit-developer`:** the agent is pre-loaded with kit conventions — frontmatter discipline (`origin`/`repository`/`module`/`protected`), module-path mapping (consumer-flat ↔ kit-nested), No-Override Rule prefix algorithm, registry-fragment schema, and PR-body templates (Versions block + Plan link + Rationale). A `general-purpose` sub-agent burns 5–10K tokens rediscovering these per spawn.

**Why background:**
- Parent keeps working on the user's original task uninterrupted
- The sub-agent owns the duplicate check, diff review, and PR/issue creation
- User is notified only when the sub-agent completes (non-blocking)
- Parent context stays clean (no skill-load + MCP tool-call pollution)

**Spawn pattern:**
```
Task(
  subagent_type: "t1k-kit-developer",  // fallback: "general-purpose" if agent not registered
  run_in_background: true,
  description: "sync-back <skill-name>" | "file issue for <skill-name>",
  prompt: "Invoke the /t1k:sync-back skill (or /t1k:issue).
    Affected files: <absolute paths>
    Origin metadata: <kit, module, repository from in-file frontmatter>
    Reason: <why this sync/issue is needed>
    Context: <what was changed locally and why>
    Run the full skill workflow: duplicate check → diff/dedupe → PR/issue creation.
    Report back when done."
)
```

### Workflow

After updating any `.claude/skills/` file (gotcha, reference, or SKILL.md):
1. Continue the user's current task — do NOT pause to sync
2. At a natural handoff point (end of fix, end of implementation), spawn the **background** sub-agent
3. The sub-agent runs `/t1k:sync-back --dry-run` first, then `/t1k:sync-back` if changes are generic
4. If the fix revealed a skill bug: spawn a **separate** background sub-agent for `/t1k:issue`
5. Parent reports completion to the user based on sub-agent's return message

**Exception — explicit user request:** If the user explicitly asks "sync this now" or "file the issue now," run inline so they see the result immediately.

## Auto-Issue Submission Handling (telemetry-kit-error-collector)

When `telemetry-kit-error-collector.cjs` detects a T1K-related tool error, it writes a pending request to `.claude/telemetry/pending-issue-submissions.jsonl` and emits a marker to stdout:

```
[t1k:auto-issue] count=1/5 kit="theonekit-unity" reason="stack-trace-path" fp="abc123def4567890"
```

### Marker Fields

- `count=N/M` — current/max submissions this session (5 by default)
- `kit="..."` — origin kit from classifier (or `"?"` if unknown)
- `reason="..."` — classifier reason: `t1k-command | t1k-agent | skill-invocation | stack-trace-path | origin-metadata | required-mcp`
- `fp="..."` — 16-char MD5 fingerprint (key into pending-issue-submissions.jsonl)

### Assistant-Side Handling (MANDATORY)

When you see a `[t1k:auto-issue]` marker in hook output:

1. **Do NOT interrupt the user** — continue with the user's current task
2. **Read** `.claude/telemetry/pending-issue-submissions.jsonl`
3. **Find the entry** matching the `fp` from the marker (latest occurrence if duplicate fingerprints exist)
4. **Spawn a background sub-agent** for `/t1k:issue` in auto-submission mode:
   ```
   Task(
     subagent_type: "t1k-kit-developer",  // fallback: "general-purpose" if agent not registered
     run_in_background: true,
     description: "auto-file issue <fp>",
     prompt: "Invoke the /t1k:issue skill in AUTO-SUBMISSION mode.

       Input entry (from .claude/telemetry/pending-issue-submissions.jsonl):
       <full JSON entry>

       Mandatory behavior:
       - Mode: auto-submission (no AskUserQuestion)
       - Fetch existing issues FIRST via search_issues() or gh issue list
       - If match found: add comment with occurrence details (count, fingerprint, timestamp), do NOT create new
       - Labels MUST include: 'auto-detected' AND 'classifier:<reason>'
       - Title: auto({kit}): <first 60 chars of stderrHead>
       - Body: use the Detection Context template from /t1k:issue SKILL.md
       - After success: append writeback entry to pending-issue-submissions.jsonl with submitted:true + issueUrl
       - Also call markSubmitted(fp, issueUrl) via .claude/hooks/lib/kit-error-dedup.cjs"
   )
   ```
5. **Do NOT wait** for sub-agent completion — continue with the user's original task
6. **Do NOT re-emit** the marker — single-shot per session per fingerprint (dedup handles this)

### Kill Switch

Users can disable auto-submission entirely by setting `features.autoIssueSubmission: false` in any `t1k-config-*.json`. The hook exits early in that case and no markers are emitted.

### Dry-Run Mode

If `T1K_AUTO_ISSUE_DRY_RUN=1` is set, the hook logs to `~/.claude/.auto-issue.log` and does NOT emit the marker. Assistants should not spawn a sub-agent for dry-run markers (none exist).
