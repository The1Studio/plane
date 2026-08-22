---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# t1k-fix — HARD-GATE full contracts

Detailed content for the four HARD-GATE blocks in `SKILL.md`. The SKILL.md keeps the
machine-readable `<HARD-GATE…>` markers + a one-line summary each (per `rules/workflow-gates.md`);
the full enforceable detail lives here (per `architecture-rules.md` §K body-tightness). Universal
HARD-GATE contract: `rules/workflow-gates.md` (auto-loaded).

## HARD-GATE (plan-before-fix)

Do NOT propose or implement fixes before completing Steps 1–2 (Scout + Diagnose).
Symptom fixes are failure. Find the cause first through structured analysis, NEVER guessing.
If 3+ fix attempts fail, STOP and question the architecture — discuss with user before attempting more.
User override: `--quick` mode allows a fast scout-diagnose-fix cycle for trivial issues (lint, type errors).

## HARD-GATE-SCOUT-FIRST

Always scan the codebase BEFORE asking clarifying questions or forming hypotheses. Mandatory scout outputs (collect before Step 2):

1. Project type, language(s), framework(s) — from `package.json` / `pyproject.toml` / `go.mod` / `*.csproj` / `Cargo.toml` / Unity `manifest.json` / Cocos `package.json` / etc.
2. The exact file(s) where the symptom surfaces + their direct callers/dependents
3. Related tests covering the affected area
4. Recent commits (`git log --oneline -20`) touching scouted files — possible introducer
5. Existing patterns/conventions for this kind of code (so the fix matches them)

State a 3–6 bullet codebase-context summary to the user BEFORE asking questions. This kills the "imagined context" failure mode where the model hallucinates architecture from a few file reads instead of grounding hypotheses in real codebase evidence.

## HARD-GATE-EXACT-ROOT-CAUSE

Do NOT propose a fix until you can answer ALL six in one concrete sentence each:

1. **Exact symptom** — precise error message / failing assertion / observed behavior (copy verbatim, NOT paraphrased).
2. **Reproduction steps** — minimal sequence that triggers it (commands, inputs, environment).
3. **Expected vs actual** — what SHOULD happen vs what DOES happen.
4. **Root cause** (NOT symptom) — the underlying defect: specific line, missing check, race condition, contract violation, design flaw. Cite `file:line` evidence.
5. **Why now** — what change/condition exposed it today: recent commit (point to SHA), data shape change, env divergence, dep upgrade, half-finished migration. If you cannot answer "why now", you do not yet understand the system — return to scout.
6. **Blast radius** — every code path that depends on the broken behavior or shares the same root cause.

If ANY item is vague ("probably", "I think", "something with…"), use `AskUserQuestion` to gather missing facts (logs, repro, env) OR run more scout/debug — NEVER guess. Ground every `AskUserQuestion` option in scout findings (specific files, specific commits, specific functions) — never abstract.

## HARD-GATE-NO-SIDE-EFFECTS

The fix is NOT done until verified to be side-effect-free. Step 5 MUST prove ALL five:

1. Original symptom no longer reproduces (re-run exact pre-fix repro from #2 above).
2. All tests in modified files + transitively-affected modules pass.
3. No business logic / workflow regression in the blast radius identified above (run those tests too, or manually walk the affected flows).
4. No new lint / type / build errors introduced anywhere.
5. Public API contracts (function signatures, exported types, response shapes, DB schemas, env vars) unchanged — OR the change is intentional and called out in the commit message.

If verification reveals a side effect, regression, or broken workflow, STOP. Do NOT silently patch around it. Use `AskUserQuestion` to present:
- What broke (file, test, workflow)
- Why the fix caused it (1-line cause)
- 2–4 concrete options, e.g.:
  - "Revert the fix and try a different root-cause angle"
  - "Keep the fix and update dependent code at `<files>` to match the new contract"
  - "Narrow the fix scope to `<subset>` so the regression goes away"
  - "Accept the regression — it was buggy behavior the test was locking in"

Let the user decide. Do not assume.
