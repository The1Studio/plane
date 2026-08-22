---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# Team Shape Template — `--team` flag output contract

When `/t1k:plan` is invoked with `--team`, the generated plan MUST include explicit teammate roster sections so the lead at `/t1k:team cook` time spawns the right roster upfront. The roster exists so the lead starts with a coherent cast and file-ownership split — not because fan-out below the lead is unavailable. The depth budget allows a teammate (depth 1) to fan out up to 3 sub-agents, and a depth-1 background sub-agent has been probe-verified to spawn both `Explore` and registry-routed types.

Spec source: `skills/t1k-team/SKILL.md` "Constraints" + `skills/t1k-architecture/references/fork-hygiene.md`.

## Why team-shape is a plan deliverable (not a runtime decision)

| Mid-flight | Spawn-time |
|---|---|
| Teammate hits "need a reviewer" → cannot `Agent` spawn (harness strips at depth 1) | Lead pre-spawns reviewer as a sibling teammate (also depth 1) |
| Teammate falls back to "complete in-context" → silently degrades parallelism, breaks worktree isolation, loses manifest ownership | All roles run isolated under their declared ownership globs |
| Plan author defers shape to runtime → lead improvises at spawn time, hits Plan-Fit Assessment Gate violations | Plan author names the cast → Plan-Fit Gate passes cleanly |

## Two required sections

### 1. Upfront `## Team Layout` in `plan.md`

Cross-phase roster summary. Placed after `## Phases` overview, before any individual phase file references.

```markdown
## Team Layout

| Phase | Teammates | Roles | Worktrees | Parallel cap |
|---|---|---|---|---|
| Phase 1 — Research | 2 | researcher × 2 | no | 2 |
| Phase 2 — Implement | 4 | dev × 3, reviewer × 1 | yes (devs only) | 4 |
| Phase 3 — Validate | 2 | tester × 1, reviewer × 1 | no | 2 |

**Sequential phase boundaries:** lead re-spawns fresh sibling teammates at each phase transition. No teammate persists across phases.

**Module scope mapping:** Phase 2 devs are scoped one-per-module per `metadata.json` `installedModules`. Reviewer covers cross-module integration only — no module scope.

**Skill inventory per role:** each teammate activates its module skills + core skills via `Skill` tool at start. See `skills/t1k-cook/references/subagent-injection-protocol.md`.
```

### 2. Per-phase `### Team Shape` in each `phase-N.md`

Concrete spawn-ready roster for that phase only.

```markdown
### Team Shape

**Roster:**
- `dev-{module-a}` — `t1k-fullstack-developer`, model: `sonnet`, scope: `{module-a}`, ownership: `{globs from manifest}`, worktree: yes
- `dev-{module-b}` — `t1k-fullstack-developer`, model: `sonnet`, scope: `{module-b}`, ownership: `{globs from manifest}`, worktree: yes
- `reviewer` — `t1k-code-reviewer`, model: `opus`, scope: cross-module, read-only, no worktree

**Spawn order:** devs in parallel via `TeamCreate` + N × `TaskCreate`. Reviewer spawned AFTER devs complete + worktrees merged (sequential dep via `addBlockedBy`).

**Skills each teammate should activate first:**
- devs: `/t1k:fix`, `/t1k:test`, module skills from `{module}/module.json`
- reviewer: `/t1k:review`, `/t1k:security` (if security-touching)

**Escalation contract:** if a teammate needs to fan out but finds no `Agent` tool in its own tool set, it MUST bail loudly via `[t1k:teammate-escalation]` marker (see `skills/t1k-team/references/fork-context-bail.md`) — never silently fall back to in-context work.
```

## Model per teammate — MANDATORY field (issue #268)

Each teammate entry MUST carry an explicit `model:` value. The `t1k-agent-creator` convention (see [#268](https://github.com/The1Studio/theonekit-core/issues/268)) is:

| Model | When to use | Cost (rough) |
|---|---|---|
| `sonnet` | **Default** for nearly every teammate — devs, reviewers, researchers, debuggers, testers | 1x baseline |
| `haiku` | Cheap fan-out / discovery / read-only scans | ~0.2x |
| `inherit` | ONLY when teammate must match parent's reasoning depth (rare, requires inline justification comment) | matches parent (likely Opus = ~5x) |
| `opus` | Documented as "unused" — explicit opt-in only, must justify in plan rationale | ~5x |

**Why this matters at plan time:** When the lead spawns a teammate via `Agent(...)` without setting `model:`, the harness inherits the parent's model. If the parent session is Opus 4.7 (common for CTO/plan workflows), every "default" teammate silently runs at 5x cost. Issue #268 confirmed this drift across 6 agent definitions on main as of 2026-05-23.

**Plan author rule:** Name `model:` per teammate explicitly. Default to `sonnet` unless the teammate's task genuinely needs Opus reasoning depth (architecture decisions, ambiguous specs, deep cross-file refactors). If `inherit` is used, add a one-line rationale below the roster entry.

Counter-example:
```markdown
- dev-balance — t1k-fullstack-developer, scope: balance, ownership: Data/balance.csv  # MISSING model: — lead inherits Opus, 5x cost waste
```

Correct:
```markdown
- dev-balance — t1k-fullstack-developer, model: sonnet, scope: balance, ownership: Data/balance.csv
```

## Default counts (when `--team` flag present, no sub-flags)

| Role | Default | Reasoning |
|---|---|---|
| devs | `min(touched_modules, 4)` | One per module up to fan-out cap |
| reviewers | 1 (cross-module) | One sibling at depth 1 to audit integration |
| researchers | 0 | Only added if plan's research phase explicitly needs depth |
| debuggers | 0 | Only added if plan anticipates debug-heavy phase |
| testers | 1 | Post-merge full-suite run, blocked by devs |

Override with sub-flags: `--team-devs N`, `--team-reviewers N`, `--team-researchers N`, `--team-debuggers N`.

## Sub-flag interaction

| Flag combo | Effect |
|---|---|
| `--team` alone | Defaults table above applied; planner reasons module count from scope |
| `--team --team-devs 3` | Forces 3 devs regardless of module count; planner warns if `touched_modules > 3` (under-coverage) or `< 3` (idle teammates) |
| `--team --team-reviewers 2` | Two reviewers in review phase — typically one for code-quality, one for security |
| `--team --team-researchers 3` | Mirrors `--deep` research depth but as parallel teammates instead of upfront researcher spawn — useful when research overlaps implementation |
| `--team --team-debuggers N` | Reserved for plans with a dedicated debug phase (e.g., `--tdd` red phase or known-flaky integration) |

## Composability with other depth flags

`--team` is composable like `--tdd`. No new guards added.

| Combo | Behavior |
|---|---|
| `--team --hard` | Hard-depth research upfront + team shape per phase. Typical for medium-risk multi-module features. |
| `--team --deep` | Deep-depth research + per-phase team shape + mandatory `/t1k:review` gates. Architecture-critical features. |
| `--team --tdd` | Team shape PLUS 3.T/3.I/3.V sub-steps in every implementation phase. Devs handle T → I → V each within their own worktree. |
| `--team --parallel` | Parallel research phase has team shape too — researchers as siblings; otherwise identical to `--parallel`. |
| `--team --fast` | Allowed but discouraged. `--fast` skips research/red-team; team shape still emitted but reviewer count auto-drops to 0. Document the reason in the plan. |

## Plan-Fit Assessment Gate (mandatory before cook handoff)

When `--team` is set, the planner MUST end the plan with a Plan-Fit Assessment summary that the lead at `/t1k:team cook` time will use as the gate input:

```markdown
## Plan-Fit Assessment (--team)

- **Total teammates across all phases:** N
- **Max parallel cap hit:** P (must be ≤ 4)
- **File-ownership conflict risk:** {none | low (shared docs only) | medium (overlapping globs flagged below) | high (cross-module shared state)}
- **Estimated token cost:** {teammates × per-teammate-budget × phases}
- **Sequential phase count:** {number of `TeamDelete` + fresh `TeamCreate` boundaries}
- **Worktree footprint:** {N worktrees at peak}
```

Lead reads this section verbatim and surfaces it via `AskUserQuestion` (proceed / re-shape / reduce scope / abort) before any `TeamCreate` call — per `skills/t1k-team/SKILL.md:124` Plan-Fit Assessment Gate.

## Cook handoff line

When `--team` is set, the plan's tail line MUST be:

```
/t1k:team cook {plan-path}
```

NOT `/t1k:cook {plan-path}` — the latter is single-agent and ignores the team shape.

## Counter-example — what a `--team` plan MUST NOT look like

```markdown
### Team Shape
- Lead will spawn teammates as needed during implementation.
```

This is the bad shape. The harness blocks "as needed" mid-flight escalation. The plan MUST name the cast.

## Worked example

For a feature touching `dots-combat` + `ui` + `balance` modules, with `/t1k:plan --team --deep --tdd`:

```markdown
## Team Layout

| Phase | Teammates | Roles | Worktrees | Parallel cap |
|---|---|---|---|---|
| Phase 1 — Research (deep) | 3 | researcher × 3 | no | 3 |
| Phase 2 — Implement (tdd) | 4 | dev × 3 (one per module) + reviewer × 1 | yes (devs) | 4 |
| Phase 3 — Integration test | 2 | tester × 1 + reviewer × 1 (security) | no | 2 |
```

Phase 2 `phase-2.md` `### Team Shape`:
```markdown
- `dev-dots-combat` — `t1k-fullstack-developer`, scope: `dots-combat`, ownership: `Assets/Combat/**`, worktree: yes
- `dev-ui` — `t1k-fullstack-developer`, scope: `ui`, ownership: `Assets/UI/**`, worktree: yes
- `dev-balance` — `t1k-fullstack-developer`, scope: `balance`, ownership: `Assets/Balance/**` + `Data/balance.csv`, worktree: yes
- `reviewer` — `t1k-code-reviewer`, scope: cross-module integration glue, read-only

Devs spawn in parallel. Reviewer spawns AFTER all 3 worktrees merge (sequential dep). Each dev runs TDD T→I→V inside its own worktree.
```
