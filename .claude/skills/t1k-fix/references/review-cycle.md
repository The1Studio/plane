---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Review Cycle

Mode-aware review handling for t1k-code-reviewer results.

## Reviewer Brief (MANDATORY — spawn contract)

Every workflow that reaches the Code Review step MUST spawn the resolved `reviewer` role (default `t1k-code-reviewer`) with a brief that (a) declares the report path — the reviewer's Deliverable-First Protocol (`agents/t1k-code-reviewer.md`) blocks on `AskUserQuestion` if none is given, a dead-end inside a Task subagent — and (b) injects the root cause + blast radius + public contracts so the reviewer can prove `HARD-GATE-NO-SIDE-EFFECTS` and the orchestrator can populate `review-decision.json`'s required `acceptanceCoverage` / `regressionProof` / `contractStatus` from a review that actually checked them — NOT from its own knowledge (the self-grading failure `artifact-gate-rules.md` exists to stop). Root cause + blast radius come from the `HARD-GATE-EXACT-ROOT-CAUSE` slots (`hard-gates.md`) / `context-snippets.json`. A bare "review the fix" brief is a violation.

```
Task(subagent_type="<resolved reviewer role>",
     prompt="Review the fix for [symptom]. Write your report to [plan-dir]/reports/review-fix-[slug].md.

Root cause the fix must address — confirm it targets the CAUSE, not a symptom patch:
[root cause + file:line from HARD-GATE-EXACT-ROOT-CAUSE #4]

Original symptom + repro — confirm the fix's logic makes it no longer reproduce:
[symptom #1 + repro steps #2]

Blast radius — walk each dependent path for regressions:
[blast radius #6 / touchpoints]

Public contracts that MUST stay stable — flag any change:
[signatures / exported types / response shapes / schemas / env vars]

Also check: security/OWASP, no new lint/type/build errors, follows scouted patterns.

Return: score (X/10); critical; warnings; suggestions; root-cause-addressed evidence (acceptance coverage); blast-radius regression verdict; contract-stability status; clean build/lint/typecheck (pass|fail|not-run).",
     description="Review fix [slug]")
```

- Report path satisfies the agent's Deliverable-First Protocol (`agents/t1k-code-reviewer.md` — expects `plans/reports/review-*.md` or similar).
- Root-cause / blast-radius / contract / clean-build map 1:1 to the 5 proofs in `hard-gates.md` § HARD-GATE-NO-SIDE-EFFECTS and the required fields of `review-decision.json` (`artifact-gate-rules.md`).

## Autonomous Mode

```
cycle = 0
LOOP:
  1. Run t1k-code-reviewer (brief per § "Reviewer Brief") → score, critical_count,
     warnings, suggestions, acceptance_coverage, regression_verdict,
     contract_status, clean_build

  2. IF score >= 9.5 AND critical_count == 0:
     → Output: "✓ Review [score]/10 - Auto-approved"
     → PROCEED to next step

  3. ELSE IF critical_count > 0 AND cycle < 3:
     → Output: "⚙ Auto-fixing [N] critical issues (cycle [cycle+1]/3)"
     → Fix critical issues
     → Re-run tests
     → cycle++, GOTO LOOP

  4. ELSE IF cycle >= 3:
     → ESCALATE to user via AskUserQuestion
     → Display findings
     → Options: "Fix manually" / "Approve anyway" / "Abort"

  5. ELSE (score < 9.5, no critical):
     → Output: "✓ Review [score]/10 - Approved with [N] warnings"
     → PROCEED (warnings logged, not blocking)
```

## Human-in-the-Loop Mode

```
ALWAYS:
  1. Run t1k-code-reviewer (brief per § "Reviewer Brief") → score, critical_count,
     warnings, suggestions, acceptance_coverage, regression_verdict,
     contract_status, clean_build

  2. Display findings:
     ┌─────────────────────────────────────┐
     │ Review: [score]/10                  │
     ├─────────────────────────────────────┤
     │ Critical ([N]): [list]              │
     │ Warnings ([N]): [list]              │
     │ Suggestions ([N]): [list]           │
     └─────────────────────────────────────┘

  3. Use AskUserQuestion:
     IF critical_count > 0:
       - "Fix critical issues"
       - "Fix all issues"
       - "Approve anyway"
       - "Abort"
     ELSE:
       - "Approve"
       - "Fix warnings/suggestions"
       - "Abort"

  4. Handle response:
     - Fix → implement, re-test, re-review (max 3 cycles)
     - Approve → proceed
     - Abort → stop workflow
```

## Quick Mode Review

Uses same logic as Autonomous but:
- Lower threshold: score >= 8.5 acceptable
- Only 1 auto-fix cycle before escalate
- Focus on: correctness, security, no regressions

## Critical Issues (Always Block)

- Security vulnerabilities (XSS, SQL injection, OWASP)
- Performance bottlenecks (O(n²) when O(n) possible)
- Architectural violations
- Data loss risks
- Breaking changes without migration
