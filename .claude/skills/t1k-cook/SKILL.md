---
name: t1k:cook
description: "Implement features end-to-end: plan, code, test, review via registry agents. Use for 'implement X', 'build Y feature', 'add Z functionality'. Handles full workflow."
keywords: [implement, build, feature, add, create, develop, end-to-end]
argument-hint: "[task|plan-path] [--interactive|--fast|--parallel|--auto|--yolo|--no-test|--tdd] [--advice]"
effort: high
tools: [Read, Glob, Grep, Bash, Write, Edit, MultiEdit, Task, Agent, WebFetch, WebSearch, TodoWrite, AskUserQuestion, Skill]
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Cook -- Feature Implementation

End-to-end feature implementation. Routes to the registered implementer agent for the current kit. Plan before code; harness over hope.

> **Kit-wide discipline:** features and changes that touch kit-owned content (anything under `.claude/`) ship via the owning kit source repo per [`rules/kit-wide-fix-discipline.md`](../../rules/kit-wide-fix-discipline.md). Local-only edits regress on next `t1k modules update` — implement in the kit, release picks it up.

**Principles:** YAGNI, KISS, DRY | Token efficiency | Concise reports

## Pre-flight Step 0 — Fuzzy plan/path arg resolution (MANDATORY)

If the user's arg is not an exact existing path (e.g. `chaosforge-demo`, `plans/chaosforge-demo`, `phase-3`, empty / "active plan"), run the Fuzzy Plan / Path Resolution Protocol at `references/fuzzy-plan-resolution.md` BEFORE intent detection or bail.

The skill MUST NOT emit "no plan matching" / "exact path required" until the protocol has been applied and its Step 6 reached. The protocol uses only `Bash` + `Glob`, which are always available.

## Tool guard — `AskUserQuestion` is deferred

`AskUserQuestion` is deferred (name in the system-reminder, schema NOT loaded; direct call → `InputValidationError`). Before drafting any structured multi-option question, if it's not in the loaded tool list run `ToolSearch(query="select:AskUserQuestion", max_results=1)` THEN invoke it. Drafting prose option-bullets first (instead of loading the schema) is a violation. Full rule: `rules/ask-before-deciding.md` + `rules/always-ask-on-unresolved.md` "Forbidden prose" table.

## Decision tree — which path do I take?

Pick by intent; keep loading minimal.

| Intent | Path |
|---|---|
| Ship a feature end-to-end with research + tests + review | Default `--interactive` workflow below |
| Plan exists already; execute it | Pass plan path; mode auto-detects to `code` |
| Skip research; you trust the spec | `--fast` (still requires plan step) |
| Multiple unrelated features at once | `--parallel` (sub-agents on disjoint files) |
| Test-driven: tests first, then code | `--tdd` (incompatible with `--parallel` / `--no-test`) |
| Maximum autonomy — run fully automated, never stop to ask | `--yolo` (auto + defer every question to one end-of-run batch; never bypasses test/review/artifact gates) |
| Run the whole implementation under advisory supervision | `--advice` (composes with every mode above) |

## Usage
```
/t1k:cook <natural language task OR plan path>
```

## Advisory supervision (`--advice`)

Full contract: [`references/advisory-supervision.md`](references/advisory-supervision.md)
— invocation, forward-carry, PR gate, empty-counsel fallback, and the
"never bypasses a gate" clause. Read it before firing the first checkpoint.

Composes with every mode (`--interactive`, `--fast`, `--parallel`, `--auto`,
`--yolo`, `--tdd`). It adds a supervisor; it changes no execution shape.

Cook-specific checkpoints, on top of the three universal ones:

- **After each implementation phase completes** — pass the phase goal, what
  changed (file list + `file:line` for the load-bearing edits), and the test /
  build evidence; ask for a go/no-go and the next risk to watch before the next
  phase.
- **Before the artifact gate and review cycle** — pass the diff summary and the
  acceptance criteria from the `HARD-GATE-BRAINSTORM-FIRST` contract; ask what
  the review is most likely to miss.
- **On the 3+-failed-attempt gate** — pass every approach tried and the exact
  obstacle before questioning the architecture with the user.

Forward-carry `--advice` into `t1k:test`, `t1k:review`, and any `t1k:ship`
handoff so supervision survives the handoff.

**Optional flags** (no flag → `interactive`): `--interactive` (default) | `--fast` (skip research) | `--parallel` (multi-agent) | `--no-test` | `--auto` (auto-approve LOW-RISK steps only) | `--yolo` (maximum autonomy — auto + defer every question to the end) | `--tdd` (test-driven: write tests first, implement, verify)

**Auto mode contract:** `--auto` is NOT "AI does whatever it wants." `--auto` runs when there is enough evidence (5 artifacts validated by the artifact-gate hook) AND risk is in the allowed zone (`risk-gate.json` `highRisk: false`). High-risk changes always stop for human approval before finalize/commit/ship, even in auto mode. Full rules: `references/artifact-gate-rules.md`.

**Yolo mode contract:** `--yolo` is `--auto` plus "never stop to ask" — it makes the most conservative reasonable assumption at every policy/human-decision gate, logs it, and surfaces ALL deferred decisions in one batch at the end before any irreversible finalize. It NEVER bypasses correctness gates (100% test pass, artifact-gate, mandatory `t1k-code-reviewer`, no-side-effects proofs, runtime-smoke). Full doctrine: `references/yolo-mode.md`.

## Agent Routing
Follow protocol: `skills/t1k-cook/references/routing-protocol.md` — role: `implementer`

## Skill Activation
Follow protocol: `skills/t1k-cook/references/activation-protocol.md`

**Game-engine module installed (`unity-*`/`cocos-*`) + task touches game logic
(combat, inventory, quest, shop, UI-bound rules)?** Activate `t1k-game-arch`
alongside the engine skill — the logic/presentation split is an implementation
decision, not an afterthought. Unity DOTS `ISystem` code is exempt (already the
tested logic layer); see `t1k-game-arch`'s DOTS/ECS carve-out.

## Plane Work-Item Gate (MANDATORY)

Fires BEFORE the first implementation edit, so the board is truthful while the work
runs. Full contract — do not restate or reimplement it here:
[`skills/t1k-plane/references/workflow-enforcement.md`](../t1k-plane/references/workflow-enforcement.md)
§ Stage 0 + Stage 2. Governing rule: `modules/t1k-extended/rules/plane-workitem-workflow.md`.

1. Pre-flight — mode, MCP availability, repo binding, session binding.
2. Session binding already holds this work → reuse it. Empty → run the match/create
   flow (§ Stage 1); **a cook with no bound work item is the case this gate exists to
   prevent**. Never auto-create — offer *match existing* alongside *create new*.
3. `t1k-plane-binding.cjs session stage --stage in_progress`. `changed:false` means the
   item is already In Progress — skip the redundant Plane write.
4. `changed:true` → advance to **In Progress** (`started` state group — resolve by
   group, never by name) and comment the plan path plus branch name.

Done is NOT set here. It fires later from `/t1k:git` push or PR merge (§ Stage 4).

Degrades to a single warning when the `plane` MCP server is absent, `T1K_PLANE_MODE`
is `advisory`/`off`, or `--no-plane` was passed. A tracker gap never blocks shipping.

HARD-GATE contract: see `rules/workflow-gates.md` (auto-loaded).

Full enforceable detail for all four gates: `references/hard-gates.md`. Markers below are the machine-readable contract; the one-line summaries are authoritative-by-reference.

<HARD-GATE>
No implementation code until a plan exists and has been reviewed — regardless of task simplicity. Exception: `--fast` skips research but still requires a plan. Override: user says "just code it"/"skip planning". Detail: `references/hard-gates.md` § HARD-GATE.
</HARD-GATE>

<HARD-GATE-SCOUT-FIRST>
Before planning OR questions, scan the codebase; emit the 5 mandatory scout outputs (project type, relevant modules, conventions, docs/plans, affected contracts) + a 3–6 bullet context summary. Skip only when input is a `plan.md`/`phase-*.md` path. Detail: `references/hard-gates.md` § Scout-First.
</HARD-GATE-SCOUT-FIRST>

<HARD-GATE-EXACT-REQUIREMENTS>
Before a plan, answer all 5 in one concrete sentence each (via `AskUserQuestion`, scout-grounded — never on vague intent): expected output, acceptance criteria, scope boundary, non-negotiable constraints, touchpoints. Skip only when input is a plan path. Detail: `references/hard-gates.md` § Exact-Requirements.
</HARD-GATE-EXACT-REQUIREMENTS>

<HARD-GATE-NO-SIDE-EFFECTS>
Not done until review+test gates prove all 5: matches acceptance, all (incl. shared-contract) tests pass, no touchpoint regression, no new lint/type/build errors, public contracts unchanged (or intentional+noted). `--no-test` downgrades item 2 to a surfaced warning. Side effect → STOP, `AskUserQuestion` with options. Detail: `references/hard-gates.md` § No-Side-Effects.
</HARD-GATE-NO-SIDE-EFFECTS>

Anti-rationalization discipline: see `rules/agent-anti-rationalization.md` (auto-loaded).

## Process Flow (Authoritative)

```mermaid
flowchart TD
    A[Intent Detection] --> B{Has plan path?}
    B -->|Yes| F[Load Plan]
    B -->|No| C{Mode?}
    C -->|fast| D[Scout → Plan → Code]
    C -->|interactive/auto/yolo| SC[Scout Codebase — HARD-GATE-SCOUT-FIRST]
    SC --> SR[Summarize Findings to User]
    SR --> RQ{Exact requirements captured?<br/>output, acceptance, scope, constraints, touchpoints<br/>HARD-GATE-EXACT-REQUIREMENTS}
    RQ -->|No| SR
    RQ -->|Yes| E[Research → Review → Plan]
    E --> F
    D --> F
    F --> G[Review Gate]
    G -->|approved| H[Implement]
    G -->|rejected| E
    H --> I[Review Gate — HARD-GATE-NO-SIDE-EFFECTS + artifact gate]
    I -->|approved| J{--no-test?}
    J -->|No| K[Test]
    J -->|Yes| L[Finalize — artifact gate, subagents]
    K --> L
    L --> M[Report + Journal]
```

**This diagram is authoritative.** If prose in this skill or its references conflicts with this flow, follow the diagram.

## Smart Intent Detection

Mode from input: `plan.md`/`phase-*.md` path → **code** · "fast"/"quick" → **fast** · "trust me"/"auto" → **auto** (low-risk auto-approve, stop on high-risk) · "yolo" → **yolo** (full autonomy, defer every question to one end-of-run batch) · 3+ features/"parallel" → **parallel** · "no test"/"skip test" → **no-test** · "tdd"/"test first" → **tdd** · default → **interactive**. Full detection logic: `references/intent-detection.md`.

## Workflow

```
[Intent Detection] -> [Drift Check] -> [Scout HARD-GATE] -> [Requirements HARD-GATE] -> [Research?] -> [Review] -> [Plan] -> [Review] -> [Implement] -> [Review + Artifact Gate] -> [Test?] -> [Review] -> [Finalize + Artifact Gate]
```

**Drift Check (Step 0.5, MANDATORY):** before any research/plan/code, run a quick `git fetch` + scan of recent merges (default branch, last ~24h) to confirm a teammate hasn't already shipped this fix or partially addressed it. Applies in ANY repo where cook runs — kit source, consumer game project, library, anywhere. Skips silently for non-git or no-remote directories. Procedure + decision tree: `references/workflow-steps.md` § "Step 0.5".

**Issue Claim (when routing a fix/issue-driven workflow):** cook defers to the same Step 0.5 claim gate defined in `t1k:fix` — enforced via the shared `.claude/scripts/t1k-issue-claim.cjs` and `rules/issue-claim-discipline.md`. No separate gate logic here.

| Mode | Research | Testing | Review Gates |
|------|----------|---------|--------------|
| interactive | yes | yes | User approval at each step |
| auto | yes | yes | Auto only if all 5 artifacts PASS AND `risk-gate.json` `highRisk: false`. Score alone NEVER auto-approves. |
| yolo | yes | yes | Like `auto`, but never stops to ask: high-risk + every clarifying question is recorded and deferred to one end-of-run batch. Artifact-gated approval + correctness gates still enforced. |
| fast | no | yes | User approval at each step |
| parallel | optional | yes | User approval at each step |
| no-test | yes | no | User approval at each step |
| code | no | yes | User approval per plan |
| tdd | yes | yes (3.T/3.I/3.V) | User approval at each step |

Full step definitions: `references/workflow-steps.md`
TDD sub-step details: `references/workflow-steps.md` → `## --tdd Flag Behavior`
Review processes: `references/review-cycle.md`

### Guards

- `--tdd + --parallel`: REFUSE with error: "TDD requires strict ordering (tests → implement → verify); parallel execution cannot preserve this. Use `--tdd` alone, or `--parallel` without `--tdd`. For a fast sequential path, consider `--tdd --fast`."
- `--tdd + --no-test`: REFUSE with error: "TDD mode inherently requires the test suite; `--no-test` is contradictory. Remove one of the flags."
- `--auto + --interactive`: existing guard, unchanged.
- `--yolo + --interactive`: REFUSE with error: "Yolo is maximum-autonomy and interactive stops at every gate — they are contradictory. Pick one."
- `--yolo` implies `--auto` (it is a strict superset); if both are passed, treat as `--yolo`. `--yolo + --tdd` and `--yolo + --parallel` are ALLOWED (yolo governs gate-deferral, not execution ordering); `--tdd + --parallel` stays refused regardless of `--yolo`.
- `--parallel` **contract-first gate** (`rules/contract-first-integration.md`): before spawning parallel implementers whose outputs meet at a shared boundary (API ↔ client, producer ↔ consumer, two modules), DEFINE the integration contract — exact path/method, payload field names + types + **casing**, enums, success/error envelope, null semantics — and embed it **verbatim** in every implementer's brief (or point all at the SSOT types/schema file). Per-side typecheck cannot catch a contract mismatch; the post-implement `t1k-code-reviewer` MUST assert both sides honor the contract.

## Artifact Gate (harness for the review + finalize stages)

After implementing, write the 5 required artifacts and validate via the workflow-artifact-gate hook. **Full rules, schemas, kill switch, and engine-kit extension contract: `references/artifact-gate-rules.md`.** SSOT shared with `t1k:fix`.

## Required Subagents — CRITICAL ENFORCEMENT

Testing, Review, and Finalize phases **MUST** spawn subagents via the Task tool (separation of cognitive powers — the implementer is not the reviewer; the planner is not the coder). Phase → agent: Research→`t1k-researcher` · Plan→`t1k-planner` · Implement→`implementer` (kit-resolved) · UI→`ui-ux-designer` · Test→`t1k-tester`/`t1k-debugger` · Review→`t1k-code-reviewer` (acceptance + no-regression + contracts + patterns + clean-build checks) · Finalize→`t1k-project-manager`+`t1k-docs-manager`+`t1k-git-manager`. Full table + per-agent rationale + injection protocol: `references/subagent-patterns.md`.

**If workflow ends with 0 Task tool calls, it is INCOMPLETE.** Same context = same blind spots; multi-agent sharing one context with no acceptance criteria and no artifacts is just many-people-being-wrong-together.

**Finalize (never skip):** t1k-project-manager → plan sync-back | t1k-docs-manager → update `./docs` | t1k-git-manager → commit offer

- When you discover a non-obvious gotcha while implementing, emit a
  `[t1k:lesson kit="..." skill="..." fragment="..." reason="..."]` marker
  in your final message. The lesson-collector hook queues it for
  follow-up sync-back automatically.

## Blocking Gates (Non-Auto Mode)

Human review required at: Post-Research, Post-Plan, Post-Implementation, Post-Testing (100% pass required).

Always enforced (every mode): 100% test pass (unless `--no-test`), artifact-gate validation, code-reviewer subagent invocation. Score is advisory; only artifact validation approves.

## When implementation goes wrong — recovery via rollback

Corrupted `~/.claude/` state (bad merge, mis-applied prefix, broken hooks) → use H7 rollback, not manual cleanup: `t1k rollback --kit <name> --to-snapshot pre-<previous-version>`. If the snapshot doesn't exist (pipeline doesn't auto-snapshot as of cli@v4.14.0), fall back to `t1k install --reset` (takes its own backup). NEVER `rm -rf ~/.claude/` — <!-- gate:allow-rm-claude (rule statement) --> the gate forbids it. Full procedure (snapshot cap, `pre-` prefix rule, non-destructive restore caveat): `references/rollback-recovery.md`.

## Environment Variables

T1K resolves env vars in priority order — never hardcode values. Details: `references/env-hierarchy.md`

Artifact-gate-specific:
- `T1K_WORKFLOW_ARTIFACT_DIR` — pin the active artifact dir (overrides pointer file)
- `T1K_WORKFLOW_ARTIFACT_GATE_DISABLED=1` — kill switch (use only when debugging the hook itself)

## References

- `references/intent-detection.md` — detection rules and routing logic
- `references/yolo-mode.md` — `--yolo` doctrine: defer-every-question protocol, deferred-decisions log, end-of-run batch
- `references/workflow-steps.md` — detailed step definitions for all modes
- `references/review-cycle.md` — interactive and auto review processes
- `references/subagent-patterns.md` — subagent invocation patterns
- `references/env-hierarchy.md` — .env resolution hierarchy
- `references/god-prefab-extraction-risk.md` — plan-phase detection for god-prefab moves to Addressables; required audit during Step 2 when removing prefabs from scenes
- `references/runtime-smoke-gate.md` — Step 3 HARD-GATE: runtime Play Mode smoke required when scene/prefab assets are touched; prevents the The1Studio/theonekit-core#176 NRE-cascade incident class
- `references/command-chaining.md` — common multi-command chains (plan→cook, cook→test→review, debug cycle), auto-chain behavior, and the task orchestration pattern (`TaskCreate`/`TaskList` field conventions)
- `.claude/hooks/workflow-artifact-gate/artifact-schema.cjs` — the 5 artifact shape validators the gate actually runs (the JSON Schemas under `.claude/schemas/` are a source-repo authoring reference, not shipped — #785)

## Contribution Scoring

If Finalize opens a PR, invoke `t1k:contribution-score` with `type=sync-back-pr` + PR URL/title/body. Fire-and-forget; SSOT gates non-T1K repos. See `.claude/skills/t1k-contribution-score/SKILL.md`.

## Sub-Agent Fork Hygiene

**Sub-agent forking:** see `skills/t1k-architecture/references/fork-hygiene.md`.
