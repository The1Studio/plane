---
name: t1k:review
description: "Code review via registry-routed reviewer agent. Adversarial, evidence-based. Inputs: pending changes, PR, commit hash, or codebase scan. Finds security holes, false assumptions, failure modes."
keywords: [review, audit, adversarial, red-team, pr, coverage, quality]
argument-hint: "[#PR | COMMIT | --pending | codebase [parallel] | adversarial] [--advice]"
effort: high
tools: [Read, Glob, Grep, Bash, Task, Agent, AskUserQuestion, Skill]
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Review — Code Review

Adversarial code review with technical rigor, evidence-based claims, and verification over performative responses. Every review includes red-team analysis that actively tries to break the code.

## Agent Routing

Follow protocol: `skills/t1k-cook/references/routing-protocol.md`
This command uses role: `reviewer`

## Input Modes

| Input | Mode | What Gets Reviewed |
|-------|------|--------------------|
| `#123` or PR URL | **PR** | Full PR diff fetched via `gh pr diff` |
| `abc1234` (7+ hex chars) | **Commit** | Single commit diff via `git show` |
| `--pending` | **Pending** | Staged + unstaged changes via `git diff` |
| *(no args, recent changes)* | **Default** | Recent changes in context |
| `codebase` | **Codebase** | Full codebase scan |
| `codebase parallel` | **Codebase+** | Parallel multi-reviewer audit |

If invoked WITHOUT arguments and no recent changes, use `AskUserQuestion` — details: `references/input-mode-resolution.md`

## Core Principle

**YAGNI**, **KISS**, **DRY** always. Technical correctness over social comfort.
Verify before implementing. Ask before assuming. Evidence before claims.

## Advisory supervision (`--advice`)

Full contract: `skills/t1k-cook/references/advisory-supervision.md` — invocation,
forward-carry, PR gate, empty-counsel fallback, and the "never bypasses a gate"
clause. Read it before firing the first checkpoint.

Composes with every input mode. In PR / Codebase modes the checkpoints fire
**per PR / per review target**, not once per run.

Review-specific checkpoints, on top of the three universal ones:

- **After the initial review completes** — pass the target ref, the diff summary,
  the findings list with severities, and the tentative verdict; ask for a go/no-go
  on the verdict and for findings that were missed.
- **After red-team analysis** — pass the attack surface examined and what
  survived; ask which failure mode was not tried.
- **Before the review lands anywhere durable** (a PR comment, a report file) —
  pass the final review body and ask for a sanity check on tone, evidence, and
  severity assignment. Revise the body if counsel flags a Critical/Important
  problem with it.

**The verdict stays this skill's.** Counsel informs the write-up and the
severities; it is not a veto in either direction — it can neither downgrade a
Critical finding nor manufacture one. Evidence rules under Practices remain
authoritative.

## Skill Activation

Follow protocol: `skills/t1k-cook/references/activation-protocol.md`

## Practices

| Practice | When | Reference |
|----------|------|-----------|
| **Spec compliance** | After implementing from plan/spec, BEFORE quality review | `references/spec-compliance-review.md` |
| **Adversarial review** | Always-on Stage 3 — actively tries to break the code | `references/adversarial-review.md` |
| Receiving feedback | Unclear feedback, external reviewers, needs prioritization | `references/code-review-reception.md` |
| Requesting review | After tasks, before merge, stuck on problem | `references/requesting-code-review.md` |
| Verification gates | Before any completion claim, commit, PR | `references/verification-before-completion.md` |
| Edge case scouting | After implementation, before review | `references/edge-case-scouting.md` |
| **Checklist review** | Pre-landing, `/t1k:ship` pipeline, security audit | `references/checklist-workflow.md` |
| **Task-managed reviews** | Multi-file features (3+ files), parallel reviewers, fix cycles | `references/task-management-reviews.md` |
| **Skill review (auto)** | Diff includes `.claude/skills/*/SKILL.md` or `.claude/skills/*/references/*.md` | invoke `t1k-skill-creator` (owns Skillmark + decision-tree + line-cap + body-tightness §K) |
| **Agent review (auto)** | Diff includes `.claude/agents/*.md` | invoke `t1k-agent-creator` (owns canonical agent frontmatter + maxTurns/model) |

**Skill-body tightness check (auto, when SKILL.md is in diff):** flag any added line matching incident-marker patterns (dates, PR refs, `Originating incident:`, `Verified failure`, commit hashes, `Real-world miss`). Recommend moving to `references/`. Rationale + full pattern list: `skills/t1k-skill-creator/references/architecture-rules.md` §K. CI gate is `validate-skill-body-tightness.cjs` — surface gate output in review summary.

## Three-Stage Review Protocol

**Stage 1 -- Spec Compliance** → `references/spec-compliance-review.md`
**Stage 2 -- Code Quality** (registry-routed reviewer agent) — runs AFTER Stage 1 passes
**Stage 3 -- Adversarial Review** → `references/adversarial-review.md` — ALWAYS-ON

Full decision tree and workflows: `references/review-workflows.md`

## Plane Work-Item Update

Comment-only — **no state transition**. Full contract:
[`skills/t1k-plane/references/workflow-enforcement.md`](../t1k-plane/references/workflow-enforcement.md)
§ Stage 3. Governing rule: `modules/t1k-extended/rules/plane-workitem-workflow.md`.

After Stage 3 completes, post the verdict and finding count to every work item bound to
this session. Critical findings do NOT move the item backwards. If the project defines
an extra `started`-group state named `In Review` / `Review` / `QA`, move there instead
of commenting alone; never create such a state to satisfy this. Degrades to a single
warning when the `plane` MCP server is absent, `T1K_PLANE_MODE` is `advisory`/`off`, or
`--no-plane` was passed.

## Generic Review Checklist

- [ ] No hardcoded values
- [ ] Error handling present
- [ ] No unnecessary complexity (YAGNI/KISS)
- [ ] No duplication (DRY)
- [ ] Security: no secrets, credentials, or sensitive data
- [ ] Tests present for new functionality

Project-type checklists: `references/checklists/base.md`, `references/checklists/api.md`, `references/checklists/web-app.md`

## Subagent Skill Injection

Follow protocol: `skills/t1k-cook/references/subagent-injection-protocol.md`

## Sub-Agent Fork Hygiene

**Sub-agent forking:** see `skills/t1k-architecture/references/fork-hygiene.md`.
