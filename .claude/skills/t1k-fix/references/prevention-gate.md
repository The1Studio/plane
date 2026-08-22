---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Prevention Gate

After fixing a bug, prevent the same class of issues from recurring. This step is MANDATORY.

## Core Principle

A fix without prevention is incomplete. The same bug pattern WILL recur if you only patch the symptom.

## Prevention Requirements (Check All That Apply)

### 1. Regression Test (ALWAYS required)

Every fix MUST have a test that:
- **Fails** without the fix applied (proves the test catches the bug)
- **Passes** with the fix applied (proves the fix works)

```
If no test framework exists:
  → Add inline verification or assertion at minimum
  → Note in report: "No test framework — added runtime assertion"
```

### 2. Defense-in-Depth Validation (When applicable)

Apply layered validation from `ck:debug` defense-in-depth technique:

| Layer | Apply When | Example |
|-------|-----------|---------|
| **Entry point validation** | Fix involves user/external input | Reject invalid input at API boundary |
| **Business logic validation** | Fix involves data processing | Assert data makes sense for operation |
| **Environment guards** | Fix involves env-sensitive operations | Prevent dangerous ops in wrong context |
| **Debug instrumentation** | Fix was hard to diagnose | Add logging/context capture for forensics |

**Rule:** Not every fix needs all 4 layers. Apply what's relevant. But ALWAYS consider each.

### 3. Type Safety (When applicable)

| Scenario | Prevention |
|----------|-----------|
| Null/undefined caused the bug | Add strict null checks, use `??` or `?.` |
| Wrong type passed | Add type guard or runtime validation |
| Missing property | Add required field to interface/type |
| Implicit any | Add explicit types |

### 4. Error Handling (When applicable)

| Scenario | Prevention |
|----------|-----------|
| Unhandled promise rejection | Add `.catch()` or try/catch |
| Missing error boundary | Add error boundary component |
| Silent failure | Add explicit error logging |
| No fallback for external dependency | Add timeout + fallback |

### 5. CI/CD Quality Gate (MANDATORY for kit-owned bugs)

If the bug is in **kit-owned content** (anything shipped under `.claude/`, plus `theonekit-release-action` scripts, `theonekit-cli`, hooks), the regression test above protects ONE repo's local suite — but a CI/CD gate protects **every consumer on every release**. Per CLAUDE.md "Every in-wild bug → new gate" + [`docs/quality-gates.md`].

Ask: **"Could a CI/CD gate have caught this before it shipped?"** Match the bug to a gate type:

| Bug class | Gate to add | Where |
|---|---|---|
| Deterministic invariant (schema drift, naming, cross-file sync, unknown commit scope, registry rollup drift) | A `validate-*.cjs` validator wired into `t1k-quality-gates.yml` | `theonekit-release-action/scripts/` |
| Behavior regression (a specific recurrence, e.g. partial-update, scope-coverage) | A unit/integration test asserting the fixed behavior | owning repo's test suite |
| Test-infra fragility (flaky timeout, mock load-order, global `mock.restore()` leak) | A test-hygiene lint gate OR retry/timeout policy | owning repo CI |
| Workflow-trigger trap (path filter, fetch-depth, required-check deadlock) | Follow `rules/ci-cd-trigger-design.md`; add the missing guard | workflow YAML |

**Decision rule:** deterministic + machine-checkable → add the gate IN THIS PR (or a tracked same-session follow-up PR on the owning kit). Judgment-heavy with no deterministic signal → note in the report WHY a gate isn't feasible (don't force a brittle gate). Either way, the question MUST be answered, not skipped.

**Cross-repo note:** the gate usually lands in a DIFFERENT repo than the fix (e.g. fix in `theonekit-cli`, gate in `theonekit-release-action`). That is expected — open a separate PR on the gate's owning repo and link it from the fix PR. See [`rules/kit-wide-fix-discipline.md`](../../../rules/kit-wide-fix-discipline.md).

## Verification Checklist (Before Completing Step 5)

```
□ Pre-fix state captured? (error messages, test output)
□ Fix applied to ROOT CAUSE (not symptom)?
□ Fresh verification run? (exact same commands as pre-fix)
□ Before/after comparison documented?
□ Regression test added? (fails without fix, passes with fix)
□ Defense-in-depth layers considered? (applied where relevant)
□ CI/CD gate evaluated? (kit-owned bug → gate added or "not feasible because…" noted — §5)
□ No new warnings/errors introduced?
□ Parallel verification passed? (typecheck + lint + build + test)
```

## Output Format

```
Prevention measures applied:
- Regression test: [test file:line] — covers [specific scenario]
- Guard added: [file:line] — [description of guard]
- Type safety: [file:line] — [what was strengthened]
- Error handling: [file:line] — [what was added]

Before/After comparison:
- Before: [exact error/failure]
- After: [exact success output]
```

## Quick Mode Prevention

For trivial issues (type errors, lint), abbreviated prevention:
- Regression test: optional (type system IS the test)
- Parallel verification: typecheck + lint only
- Defense-in-depth: skip (not applicable for type fixes)
- Still require before/after comparison of typecheck output
