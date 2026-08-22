---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Code Review Cycle

Interactive review-fix cycle used in code workflows.

## Interactive Cycle (max 3 cycles)

```
cycle = 0
LOOP:
  1. Run t1k-code-reviewer → score, critical_count, warnings, suggestions,
     acceptance_coverage, regression_verdict, contract_status, clean_build
     (brief per subagent-patterns.md § "Code Review": declare report path +
      inject acceptance criteria / touchpoints / contracts)

  2. DISPLAY FINDINGS:
     ┌─────────────────────────────────────────┐
     │ Code Review Results: [score]/10         │
     ├─────────────────────────────────────────┤
     │ Summary: [what implemented], tests      │
     │ [X/X passed]                            │
     ├─────────────────────────────────────────┤
     │ Critical Issues ([N]): MUST FIX         │
     │  - [issue] at [file:line]               │
     │ Warnings ([N]): SHOULD FIX              │
     │  - [issue] at [file:line]               │
     │ Suggestions ([N]): NICE TO HAVE         │
     │  - [suggestion]                         │
     └─────────────────────────────────────────┘

  3. AskUserQuestion (header: "Review & Approve"):
     IF critical_count > 0:
       - "Fix critical issues" → fix, re-run t1k-tester, cycle++, LOOP
       - "Fix all issues" → fix all, re-run t1k-tester, cycle++, LOOP
       - "Approve anyway" → PROCEED
       - "Abort" → stop
     ELSE:
       - "Approve" → PROCEED
       - "Fix warnings/suggestions" → fix, cycle++, LOOP
       - "Abort" → stop

  4. IF cycle >= 3 AND user selects fix:
     → "⚠ 3 review cycles completed. Final decision required."
     → AskUserQuestion: "Approve with noted issues" / "Abort workflow"
```

## Auto-Handling Cycle (for auto modes — `auto` and `yolo`)

```
cycle = 0
LOOP:
  1. Run t1k-code-reviewer → score, critical_count, warnings,
     acceptance_coverage, regression_verdict, contract_status, clean_build

  2. IF score >= 9.5 AND critical_count == 0:
     → Auto-approve, PROCEED

  3. ELSE IF critical_count > 0 AND cycle < 3:
     → Auto-fix critical issues
     → Re-run t1k-tester
     → cycle++, LOOP

  4. ELSE IF critical_count > 0 AND cycle >= 3:
     → auto: ESCALATE TO USER now
     → yolo: record to deferred-decisions log, surface in end-of-run batch.
       A critical-blocked change is a correctness failure — yolo still does NOT
       finalize/commit it past this point (see yolo-mode.md).

  5. ELSE (no critical, score < 9.5):
     → Approve with warnings logged, PROCEED
```

## Critical Issues Definition
- Security: XSS, SQL injection, OWASP vulnerabilities
- Performance: bottlenecks, inefficient algorithms
- Architecture: violations of patterns, coupling
- Principles: YAGNI, KISS, DRY violations

## Output Formats
- Waiting: `⏸ Step 4: Code reviewed - [score]/10 - WAITING for approval`
- After fix: `✓ Step 4: [old]/10 → Fixed [N] issues → [new]/10 - Approved`
- Auto-approved: `✓ Step 4: Code reviewed - 9.8/10 - Auto-approved`
- Approved: `✓ Step 4: Code reviewed - [score]/10 - User approved`
