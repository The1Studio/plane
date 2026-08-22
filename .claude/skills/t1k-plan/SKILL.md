---
name: t1k:plan
description: "Create phased implementation plans with research and task breakdown. Use for 'plan this feature', 'how should we architect X', 'break this into phases before coding'."
keywords: [plan this, plan the, implementation plan, phased plan, architecture, phases, breakdown, design, roadmap, approach]
argument-hint: "[task] OR archive|red-team|validate [--auto|--fast|--hard|--deep|--parallel|--two|--tdd|--team|--no-validate] [--advice] [--team-devs N|--team-reviewers N|--team-researchers N|--team-debuggers N]"
effort: high
tools: [Read, Grep, Glob, Bash, Write, Edit, MultiEdit, Task, Agent, WebFetch, WebSearch, TodoWrite, AskUserQuestion]
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Plan — Implementation Planning

Create phased implementation plans. Routes to registered `t1k-planner` agent via routing protocol.

## Pre-flight Step 0 — Fuzzy plan/path arg resolution (MANDATORY)

If the user's arg is not an exact existing path (e.g. resume an existing plan by partial name like `chaosforge-demo`, or reference `phase-3`, or empty / "active plan" for resume), run the Fuzzy Plan / Path Resolution Protocol at `skills/t1k-cook/references/fuzzy-plan-resolution.md` BEFORE bail.

Skill MUST NOT emit "no plan matching" until the protocol has been applied and its Step 6 reached.

## Tool guard — `AskUserQuestion` availability

`AskUserQuestion` is **always available**, but in long-context sessions it may be deferred (name appears in the deferred-tools system-reminder; schema is NOT loaded).

Decision tree before drafting any multi-option question:

1. **Tool schema visible in the loaded tool list?** → call `AskUserQuestion` directly. No `ToolSearch` needed.
2. **Only the NAME appears in the deferred-tools reminder?** → run `ToolSearch(query="select:AskUserQuestion", max_results=1)`, THEN call the tool.
3. **Neither?** → this is a session-config error. STOP and report it to the user. Do NOT proceed with prose questions.

### Forbidden output — anti-hallucination clause (MANDATORY)

The plan output MUST NEVER contain phrases like:

- "AskUserQuestion is unavailable in this thread"
- "the tool is unavailable, so defaults are listed inline"
- "I would normally batch into AskUserQuestion, but..."
- "the tool was not loaded, defaulting to prose"

These phrases are a **hallucination + violation**. The tool is available — if its schema isn't in your inventory, that is a signal to run `ToolSearch`, not to fall back to prose. If you catch yourself drafting any of these phrases, STOP, emit a `[t1k:skill-bug]` marker for this skill, and restart the question-asking step.

### Failure mode this guard prevents

Assistant remembers the rule, drafts the question correctly in its head, then because the tool schema isn't in the loaded inventory, rationalises "unavailable in this thread → I'll write prose." Drafting prose bullets first is a violation — see `rules/always-ask-on-unresolved.md` "Forbidden prose" table. Especially relevant in plan endgame: "Open questions before I write the plan" lists are the canonical violation pattern.

## When to Use
- Planning new features
- Architecting system designs
- Breaking down complex requirements
- Creating roadmaps with testing/review gates

## Workflow Modes

| Flag | Research | Red Team | Validation | Cook Handoff |
|------|----------|----------|------------|--------------|
| `--auto` | Auto-detect | Follows mode | Auto (unless `--no-validate`) | `/t1k:cook` |
| `--fast` | Skip | Skip | Skip | `/t1k:cook --auto` |
| `--hard` | 2 researchers | Yes | Auto (unless `--no-validate`) | — |
| `--deep` | 3 researchers | Yes | Auto + mandatory cook-time gate | — |
| `--parallel` | 2 researchers | Yes | Auto (unless `--no-validate`) | `/t1k:cook --parallel` |
| `--tdd` | Composable with any mode | — | — | Annotates phase cards with 3.T/3.I/3.V sub-steps |
| `--team` | Composable with any mode | — | — | Emits explicit teammate roster per phase; cook handoff → `/t1k:team cook` |
| `--advice` | Composable with any mode | — | — | Runs the plan under advisory supervision; forward-carried into the cook handoff |

Mode comparison, `--deep` vs `--hard`, and `--team` details: `references/workflow-modes.md`. Team-shape output contract (sections, defaults, model-per-teammate per issue #268): `references/team-shape-template.md`.

### Guards

- `--hard + --deep`: REFUSE. `--deep` is a strict superset of `--hard`; use one or the other.
- `--fast + --deep`: REFUSE. Fast mode skips rigor; `--deep` mandates it. They are incompatible.
- `--tdd + --parallel`: REFUSE. TDD requires strict T→I→V ordering; parallel execution cannot preserve it.
- `--fast + --hard`: ALLOWED but discouraged — document the reason in the plan.
- `--no-validate`: suppresses the post-creation auto-validation interview (see "Auto-Validation After Plan Creation"). No-op under `--fast` (already skipped). Under `--deep` it suppresses ONLY the post-creation interview — the mandatory cook-time `/t1k:review` gate still runs.
- `--team` sub-flags (`--team-devs`, `--team-reviewers`, `--team-researchers`, `--team-debuggers`): IGNORED unless `--team` is also present. Warn the user if any sub-flag is set without `--team`.
- `--advice`: composes with every mode and sub-flag. Never REFUSE it — it adds a supervisor, not an execution shape.

## Advisory supervision (`--advice`)

Full contract: `skills/t1k-cook/references/advisory-supervision.md` — invocation,
forward-carry, PR gate, empty-counsel fallback, and the "never bypasses a gate"
clause. Read it before firing the first checkpoint.

Plan-specific checkpoints, on top of the three universal ones:

- **After research completes** — pass the research findings and the prior-art
  gate result; ask what the plan is most likely to get wrong, and which
  assumption is load-bearing.
- **After the solution design / phase decomposition** — pass the phase list with
  file ownership; ask whether the seams are real and whether the parallel-safe
  decomposition actually holds.
- **After red-team and validation** — pass surviving risks; ask for a go/no-go on
  handing the plan to `/t1k:cook`.
- **Before the cook handoff** — get counsel on phase order and what to verify
  first.

Forward-carry `--advice` into the `/t1k:cook` handoff (and any `/t1k:team cook`
roster) so supervision survives the handoff. Counsel informs the plan; it does
not replace the red-team, validation, or Open Questions gates.

## Subcommands
| Subcommand | Purpose |
|---|---|
| `/t1k:plan archive` | Archive plans + journal |
| `/t1k:plan red-team` | Adversarial plan review |
| `/t1k:plan validate` | Critical questions interview |

## Context Reminder

After plan creation, output the cook handoff line:

- **Default:** `/t1k:cook {plan-path}` (single-agent execution).
- **When `--team` was set:** `/t1k:team cook {plan-path}` (multi-teammate execution honoring the team-shape sections). NEVER suggest `/t1k:cook` for a `--team` plan — single-agent execution ignores the team-shape and silently downgrades the parallelism the plan was built around.

## Open Questions Gate (MANDATORY)

If the t1k-planner needs to confirm 2-4 design decisions before finalizing the plan
(e.g., "scope target A or B?", "use module X or Y?", "tier thresholds?"), the
t1k-planner MUST invoke `AskUserQuestion` (batch up to 4 per call). NEVER list open
questions as numbered prose with checkbox-style alternatives, default tables, or
"override before /t1k:cook" tables — these are all violations regardless of the
disclaimer wrapping them. This applies at every step where decisions remain —
not just the final cook handoff.

**Self-check before writing the plan file (semantic test, not just literal patterns):** scan your
draft for ANY section that pairs an unresolved decision with a recommended default or a table of
alternatives — regardless of its heading text or column names. Do not limit the scan to the literal
`D[0-9]+ | Decision | Default | Alternatives` / `## Open Design Decisions` shape — `## Open
decisions`, `OD-N` numbering, and a bare `| Option | Consequence |` table are the same failure mode
under different labels and must be caught too. The test is structural: does this section present a
choice as still-open while also recommending one branch? If yes, your plan was written by the
failure mode — delete the section, invoke `AskUserQuestion` for those items, and rewrite the section
as resolved decisions (no "default" / "alternative" / "recommended" columns).

**Also scan your draft as a plain substring match** against the forbidden phrases listed in the Tool
guard's anti-hallucination clause above (`AskUserQuestion is unavailable...`, `the tool is
unavailable, so defaults are listed inline`, `I would normally batch into AskUserQuestion, but...`,
`the tool was not loaded, defaulting to prose`) — a plan file can carry one of these phrases even
when it was not consciously drafted as prose-first reasoning.

See `rules/ask-before-deciding.md` → "Failure mode — post-design open questions"
for the exact pattern to avoid.

## Prior-Art Gate (MANDATORY)

Before a phase specifies **new** work, the plan must record what already exists — and any claim that
something is absent must carry the scope that was searched (`zero across <paths>`, never a bare
"does not exist" / "greenfield"). Read-only vendored code, submodules and platform layers are in
scope for *discovery* even though they are out of scope for *editing*; consult available indexes
(skills, docs, manifests) before grepping.

This is the highest-cost planning error: a false "greenfield" invents whole phases, is inherited by
every estimate and contract downstream, and is never re-tested by the build. A false "already
exists" costs minutes and self-corrects. Bias the search wide. Full rule:
`rules/negative-result-scope.md`.

## Auto-Validation After Plan Creation (MANDATORY)

Once the t1k-planner has written the plan file(s), **automatically run the same
critical-questions interview as the `/t1k:plan validate` subcommand** — do NOT
wait for the user to invoke `validate` manually. This runs after the plan is on
disk and the Open Questions Gate is satisfied, immediately BEFORE emitting the
cook handoff line.

**Fires for:** every invocation — default (no flags), `--auto`, `--hard`,
`--deep`, `--parallel`, `--team`, `--tdd`.
**Skipped for:** `--fast` (fast mode skips rigor by definition) and when the
user passes `--no-validate`.

**What it does** — identical to the `validate` subcommand:

1. Re-read the just-written plan file(s).
2. Surface any critical design decision still implicit or under-specified —
   scope boundaries, module/tool choices, thresholds, phase-sequencing
   assumptions, unverified claims.
3. Batch them into `AskUserQuestion` (≤4 per call; obey the Tool guard + Open
   Questions Gate above). NEVER list them as numbered prose or default/
   alternative tables — that is the exact failure mode those gates forbid.
4. Write the resolved answers back into the plan file(s) as decided facts.
5. Emit the cook handoff line only after validation resolves clean.

If the interview finds no unresolved decisions, state
`auto-validation: no open decisions` and proceed to the handoff.

`--deep` keeps its **separate** mandatory inter-phase `/t1k:review` gate at cook
time; that gate is unrelated to this post-creation interview and is NOT
suppressed by `--no-validate`.

## Plane Work-Item Gate (MANDATORY)

Runs AFTER the plan file exists (so its phase breakdown can be estimated from) and
BEFORE the cook handoff line. Full contract — do not restate or reimplement it here:
[`skills/t1k-plane/references/workflow-enforcement.md`](../t1k-plane/references/workflow-enforcement.md)
§ Stage 0 + Stage 1. Governing rule: `modules/t1k-extended/rules/plane-workitem-workflow.md`.

1. Pre-flight — mode, MCP availability, repo binding, session binding.
2. Auto-match the plan against existing Plane work items in the bound project/module.
3. No confident match → `AskUserQuestion`: bind to a candidate · bind to an identifier
   the user types · create a new work item · proceed unbound. **Never auto-create.**
4. Set the estimated time in **hours**, summed from the plan's per-phase estimates,
   confirmed with the user before writing.
5. Advance the work item to **Todo** (`unstarted` state group — resolve by group, never
   by name) and record it in the session binding.

Degrades to a single warning when the `plane` MCP server is absent, `T1K_PLANE_MODE`
is `advisory`/`off`, or `--no-plane` was passed. A tracker gap never blocks planning.

## Agent Routing
Follow protocol: `skills/t1k-cook/references/routing-protocol.md`
This command uses role: `t1k-planner`

### Multi-round plan-review fan-out (named-agent routing)

When `--deep`, `--hard`, `/t1k:plan validate`, or `/t1k:plan red-team` triggers multi-round review, each round MUST spawn an explicitly-named specialist agent. `general-purpose` is NEVER acceptable here — it erases the quality/cost intent of the round.

| Round | Focus | Canonical agent | Default model |
|-------|-------|-----------------|---------------|
| 1 — Rigor | Completeness, edge-case coverage, assumption audit | `t1k-planner` | `opus` |
| 2 — Technical | Implementation feasibility, tech-debt risk, skill-body tightness | `t1k-code-reviewer` | `opus` |
| 3 — Facts | Reference accuracy, link validity, claim verification | `t1k-researcher` | `opus` |
| 4 — Adversarial | Attack vectors, anti-patterns, pessimistic stress-test | `t1k-planner` (red-team brief) | `opus` |

**Spawn contract:** each round agent receives the prior round's output + the original plan as Fork Context Brief (`skills/t1k-resolve-context/references/fcb-protocol.md`). The assembling agent (final round or integration step) synthesizes conflicts; it does not re-run the rounds.

## Skill Inventory Injection (if `installedModules` present in metadata.json)

Before spawning t1k-planner agent:
1. Read `.claude/metadata.json` → `installedModules` (v3) or `modules` (v2 fallback)
2. Read ALL `t1k-activation-*.json` → collect skill names grouped by module
3. Inject into t1k-planner prompt as inventory (names + modules, NOT full activation):
   "Available skills by module:
    - {module} v{version} (kit: {kit}): {skill1}, {skill2}...
    You can READ skill files if needed. DO NOT activate skills — planning only."

## Game-Engine Architecture Gate (if a `unity-*` or `cocos-*` module is installed)

Any phase that adds or refactors game-code logic (combat, inventory, quest, shop,
UI-bound rules) MUST decide its logic/presentation split as part of planning, not
defer it to implementation. Point the t1k-planner at the `t1k-game-arch` skill
(Domain/Application/Presentation/Infrastructure, module-contract.md) before the
phase is finalized. **Unity DOTS exception:** inside a pure-DOTS `ISystem`, the
system already IS the tested logic layer — `t1k-game-arch`'s carve-out documents
this; do not require a POCO-extraction phase for ECS code.

## Team-Shape Planning (`--team` flag)

When the user passes `--team`, the planner MUST emit two team-shape sections in the generated plan:

1. **Upfront `## Team Layout`** in `plan.md` — cross-phase roster summary table (phase → teammates → roles → worktrees → parallel cap).
2. **Per-phase `### Team Shape`** in each `phase-N.md` — concrete spawn-ready roster: agent type, **explicit `model:` field**, module scope, ownership globs, worktree flag, spawn order, and skills each teammate should activate first.

The planner MUST also emit a tail `## Plan-Fit Assessment (--team)` section consumed by the lead at `/t1k:team cook` time.

**Write every `phase-N.md` to be pointer-addressable** (`rules/lean-brief-pointer-not-payload.md`). The lead hands a teammate the phase *path*, never the phase *contents*, so each phase file must stand alone: goal, ownership globs, success criteria, and links to any spec it depends on. The test is whether an agent given only `phase-N.md` can start without asking a question. Anything two teammates must agree on gets its own linked file rather than being duplicated into both phases — a shared shape copied into two places will diverge. This applies to any multi-agent plan, `--team` or not.

Full output contract (sections, defaults, model-per-teammate rationale, sub-flag interaction, composability with `--deep`/`--hard`/`--tdd`, worked example): `references/team-shape-template.md`.

**Why `--team` is a plan deliverable, not a runtime decision:** planning the cast upfront gives the lead a coherent roster and file-ownership split before execution starts — not because fan-out is unavailable. A depth-1 sub-agent **does** get a working `Agent` tool and **can** spawn both `Explore` and registry-routed types (probe-verified 2026-08-12); the depth budget lets it fan out up to its cap of 3. Spec: `skills/t1k-team/references/fork-context-bail.md`.

**Model per teammate (issue #268):** each roster entry MUST carry an explicit `model:` value (default `sonnet`). Without it, the lead inherits the parent's model — and if the parent is Opus, every "default" teammate silently runs at ~5x cost. The `--team` output contract enforces named models.

## Parallel-Safe Decomposition (when fanning implementation out to multiple agents)

Any plan with a `--team` roster or a multi-agent implementation phase MUST emit, per fan-out:

1. A feature-slice **file→owner map with a zero-overlap invariant** — no file under two owners; shared-file work is sequenced, never parallelized.
2. A **unit-size cap** — many small disjoint diffs beat few large ones.
3. A **pinned contract per dependency-DAG edge that crosses two agents** (`rules/contract-first-integration.md`; point at an SSOT schema/types file where one exists).
4. **Declaration hoisting** — every type, schema, migration, enum, interface or manifest **declared by one lane and consumed by another** is moved into the **serial** phase before fan-out. Parallel lanes write *implementations*, never *shared shapes*. Why the file→owner map alone can't catch this: `references/parallel-safe-decomposition.md` § "Disjointness is necessary, not sufficient".
5. A **lead-allocated worktree/branch per agent** (`rules/parallel-teammate-git-index-race.md`; teammates never move shared HEAD).
6. A **per-unit pass/fail test command** — the fan-out's verification bar — **plus an explicit statement of whether the verifier is per-lane concurrent or globally serialized.** On a single-instance toolchain (game-engine editor, shared dev DB, one emulator/device, licence-limited tool, single staging env) it is serialized: the parallel unit is *authoring*, verification is its own terminal single-owner wave, and **a lane whose deliverable is a tool does not complete in its own wave** — writing the generator is parallel, running it is not.
7. An **integration branch → full-suite verify → sequential/rebased merge to main** final step.

This composes with the `--team` file-ownership globs + `### Team Shape` output above — same decomposition, made explicit for parallel safety. Rationale, empirical anchor, and the SOTA pattern: `references/parallel-safe-decomposition.md`.

## Multi-Agent Planning Pipeline (if 2+ modules matched)

Auto-detect: count distinct modules with keyword matches.
- 0-1 modules → single t1k-planner (standard)
- 2+ modules → multi-agent pipeline:

**Phase A** — Domain Design (if designer kit installed): spawn designer agent
**Phase B** — Domain Planning (PARALLEL): one t1k-planner per matched module
**Phase C** — Integration (sequential): generic t1k-planner assembles domain plans

## Execution Trace (if features.executionTrace enabled)
After task completes, output compact planning trace:
- Modules matched, pipeline mode (single/multi)
- Skills inventory provided (count across modules)
- Fallbacks, warnings

## Risk Assessment (Mandatory Output)

Every plan phase must include a risk table and effort estimate:

```markdown
### Risk Assessment
| Risk | Likelihood (1-5) | Impact (1-5) | Score | Mitigation |
|------|-----------------|--------------|-------|------------|
| {risk} | {L} | {I} | {L*I} | {action} |

### Timeline
| Phase | Effort | Notes |
|-------|--------|-------|
| Phase 1: {name} | S (1d) / M (3d) / L (1wk) | {blocker or dep} |
| Total | {sum} | Critical path: {phase list} |
```

**Effort scale:** S = ~1 day, M = ~3 days, L = ~1 week. Use judgment, not false precision.
**Risk score >= 15** = high risk, mandate mitigation before phase starts.

## Architecture References

**Only when planning TheOneKit's own infrastructure** (core, release-action, CLI, kit
registry/lifecycle): `references/architecture-references.md`.

## Sub-Agent Fork Hygiene

**Sub-agent forking:** see `skills/t1k-architecture/references/fork-hygiene.md`.
