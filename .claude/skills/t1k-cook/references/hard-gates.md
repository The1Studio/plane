---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# t1k-cook — HARD-GATE full contracts

Detailed content for the four HARD-GATE blocks in `SKILL.md`. The SKILL.md keeps the
machine-readable `<HARD-GATE…>` markers + a one-line summary each (per `rules/workflow-gates.md`);
the full enforceable detail lives here (per `architecture-rules.md` §K body-tightness). Universal
HARD-GATE contract: `rules/workflow-gates.md` (auto-loaded).

## HARD-GATE (plan-before-code)

Do NOT write implementation code until a plan exists and has been reviewed.
This applies regardless of task simplicity. "Simple" tasks are where unexamined assumptions waste the most time.
Exception: `--fast` mode skips research but still requires a plan step.
User override: If user explicitly says "just code it" or "skip planning", respect their instruction.

## HARD-GATE-SCOUT-FIRST

Before planning OR asking clarifying questions, scan the codebase. Mandatory scout outputs:

1. Project type, language(s), framework(s) — from `package.json` / `pyproject.toml` / `go.mod` / `*.csproj` / `Cargo.toml` / Unity `manifest.json` / Cocos `package.json` / etc.
2. Existing modules/files relevant to the task
3. Current patterns/conventions for similar features (so the implementation matches them)
4. Existing docs in `./docs/` and any in-flight plans in `./plans/` covering this area
5. Public APIs, schemas, contracts that the task could affect

State a 3–6 bullet codebase-context summary to the user BEFORE asking questions. Skip ONLY when input is a `plan.md` / `phase-*.md` path (the plan already encodes scout output).

## HARD-GATE-EXACT-REQUIREMENTS

Before producing a plan, you MUST be able to answer ALL five in one concrete sentence each (use `AskUserQuestion` to pin them down — do NOT proceed on vague intent):

1. **Expected output** — the concrete artifact(s) the user will see at the end (file paths, feature behavior, UI screen, API endpoint + payload, CLI command + flags).
2. **Acceptance criteria** — specific behaviors / inputs → outputs / edge cases that MUST work to call it "done".
3. **Scope boundary** — what is explicitly OUT of scope this round.
4. **Non-negotiable constraints** — stack, file locations, naming, backward compatibility, deadlines, performance budgets.
5. **Touchpoints** — which existing files/modules (from scout) will be modified or extended; which contracts must stay stable.

Ground every `AskUserQuestion` option in scout findings (e.g., "Add to `src/api/users.ts` (matches existing pattern) or new `src/api/profile.ts`?"). Skip ONLY when input is a `plan.md` / `phase-*.md` path (the plan already encodes these).

**Yolo mode (`--yolo`):** do NOT block on `AskUserQuestion` for these five. Derive each from scout findings + the most conservative reasonable default (Conservative-Pick), record the assumption taken in the deferred-decisions log (`references/yolo-mode.md`), and proceed. Every assumption is surfaced in the single end-of-run batch so the user can correct any before the final commit. This defers the *question*, not the *rigor* — the five answers still get written into the plan / `context-snippets.json`, just from a logged assumption instead of a live answer.

## HARD-GATE-NO-SIDE-EFFECTS

Implementation is NOT done until verified to be side-effect-free. Code-review and test gates MUST prove ALL five:

1. New behavior matches every acceptance criterion above.
2. All tests pass — including tests in modules that share files/contracts with the change.
3. No existing business logic / workflow regression: explicitly walk each touchpoint and any caller of changed functions.
4. No new lint / type / build errors anywhere in the repo.
5. Public contracts unchanged unless intentional and called out (function signatures, exported types, API responses, DB schemas, env vars, config keys).

**Deploy + migration check (item 6 — fires when the deploy verb is invoked AND a migration file was added):**
A clean local typecheck/test + green CI "Health check" step is NOT sufficient proof when the deploy pipeline has no DB-migrate step. New schema columns (or removed ones) break app startup in the target environment if the migration is never run. When BOTH conditions hold — a deploy is part of the task AND a migration file was added/changed — the gate MUST ask: "A migration was added — how is it applied in the target environment?" Acceptable answers: (a) the deploy pipeline runs `<migrate cmd>` before app start; (b) a manual runbook step is documented and the user confirms it will be executed; (c) this is a no-op migration that cannot break startup. A passing CI health check that does NOT run migrations does not satisfy this item.

User override: If user invoked `--no-test`, item 2 is downgraded to a warning. Surface the unverified-tests risk in the finalize `AskUserQuestion` so the user accepts the trade-off rather than having it silently chosen. Items 1, 3, 4, 5 remain enforceable via the mandatory `t1k-code-reviewer` subagent.

**Yolo mode:** all five proofs remain mandatory — yolo NEVER bypasses correctness. On a detected side effect / regression, yolo first attempts the most conservative auto-resolution (revert the offending slice, or add a compatibility shim at the boundary) and re-verifies. If it resolves cleanly, log the decision and proceed. If it cannot resolve safely, record the regression + the option set in the deferred-decisions log and STOP before any irreversible finalize, surfacing it in the end-of-run batch. Yolo never silently ships a regression.

If review/testing reveals a side effect, regression, or broken workflow, STOP. Use `AskUserQuestion` to present:
- What broke (file, test, workflow, user-facing behavior)
- Why this implementation caused it (1-line cause)
- 2–4 concrete options, e.g.:
  - "Revert this slice and re-plan with stricter scope"
  - "Keep the implementation and update `<dependents>` to match the new contract"
  - "Add a compatibility shim at `<boundary>` so old callers keep working"
  - "Accept the regression — old behavior was unintended/buggy"

Let the user decide. Do not silently patch around regressions.
