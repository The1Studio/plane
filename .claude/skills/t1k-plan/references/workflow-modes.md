---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
<!-- t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true -->

# t1k-plan Workflow Modes

## Comparison Table

| Aspect | default | `--hard` | `--deep` |
|--------|---------|----------|----------|
| Researcher count | 1 | 2 parallel | 3 parallel |
| Scout frequency | one-time (start) | per critical phase | per phase (no exceptions) |
| Validation gate | optional (advisory) | recommended (SHOULD) | mandatory (MUST) |
| Context7 usage | on-demand | per phase for each library | per phase + per library version |
| Dependency analysis | single pass | two passes (upstream + downstream) | three passes (upstream + downstream + cycles) |
| Risk matrix size | top 5 risks | top 10 risks | exhaustive (≥15 risks enumerated) |
| Typical effort | S–M | M–L | L–XL |
| When to use | routine features | complex features with ambiguity | mission-critical or cross-kit |

## Default Mode

- 1 t1k-researcher agent for upfront discovery
- One-time scout at the start of the plan
- Validation gates are advisory — skip if phases are simple

Suitable for 80% of planning work.

## --hard Mode

- 2 t1k-researcher agents in parallel, each exploring a different aspect
- Scout invoked at the start of each critical phase
- Validation gates recommended — run `/t1k:review` on phase outputs before proceeding
- Context7 consulted for every library mentioned in the plan

Use when the task has unclear scope, multiple viable approaches, or significant risk.

## --deep Mode

The most thorough planning mode. Use for architecture-critical features where getting it wrong has high cost.

- 3 t1k-researcher agents in parallel, each with a distinct research angle
- Scout invoked at the start of EVERY phase (not just critical ones)
- Validation gate is mandatory — AI MUST run `/t1k:review` (or equivalent gate) between phases; cannot proceed on a failed gate without explicit user override
- Dependency analysis in three passes: upstream callers, downstream effects, circular dependency detection
- Risk matrix must enumerate at least 15 distinct risks; if fewer exist, document that enumeration was exhaustive

Use when:
- Cross-kit ripple is expected (changes affect multiple repos)
- The change touches security-critical code
- The change touches release infrastructure or CI gates
- User explicitly requests thoroughness ("plan this carefully", "be thorough")

### --deep vs --hard

- `--hard` is thorough for feature work
- `--deep` is thorough for architecture work
- If unsure which to use, start with `--hard` and escalate to `--deep` if the red team finds critical gaps

## --tdd Flag (composable with any depth mode)

Inserts the TDD workflow (3.T → 3.I → 3.V) into every implementation phase in the generated plan. The plan's phase cards will include a `TDD: yes` marker and sub-step breakdowns in the "Implementation Steps" section.

See `/t1k:cook` `references/workflow-steps.md` → `## --tdd Flag Behavior` for the T/I/V mechanics.

Composable combinations:
- `--hard --tdd` — 2 researchers, per-critical-phase scout, TDD sub-steps in every phase
- `--deep --tdd` — 3 researchers, per-phase scout, mandatory validation, TDD sub-steps in every phase (highest-safety combination)

## --team Flag (composable with any depth mode)

Emits explicit teammate-roster sections so the lead at `/t1k:team cook` time spawns the right cast upfront. Compensates for the harness fork-depth limit: teammates (depth 1) cannot spawn sub-agents, so the cast must be fixed at plan time.

Effects on plan output:
- Adds `## Team Layout` cross-phase summary table in `plan.md`
- Adds `### Team Shape` subsection in each `phase-N.md` (agent type, model, scope, ownership, worktree, spawn order)
- Adds tail `## Plan-Fit Assessment (--team)` section consumed by the lead at cook time
- Changes the cook handoff line from `/t1k:cook {plan-path}` to `/t1k:team cook {plan-path}`

Sub-flags (only meaningful with `--team`):

| Sub-flag | Default | Effect |
|---|---|---|
| `--team-devs N` | `min(touched_modules, 4)` | Force N implementer teammates regardless of module count |
| `--team-reviewers N` | 1 | Cross-module reviewer count |
| `--team-researchers N` | 0 (default), 2 (`--hard`), 3 (`--deep`) | Parallel researcher teammates if research-as-team is desired |
| `--team-debuggers N` | 0 | Add N debuggers (typical when plan anticipates flaky integration) |

Composable combinations:
- `--team --hard` — hard-depth research + per-phase team shape. Typical for medium-risk multi-module features.
- `--team --deep` — deep-depth research + mandatory `/t1k:review` gates + per-phase team shape. Architecture-critical features.
- `--team --tdd` — devs run T→I→V each inside their own worktree.
- `--team --parallel` — researchers spawn as siblings; otherwise identical to `--parallel`.
- `--team --fast` — ALLOWED but discouraged; reviewer count auto-drops to 0. Document reason in plan.

Full output contract: `references/team-shape-template.md`.

## Two distinct validation concepts

Do not conflate them:

- **Post-creation auto-validation** (SKILL.md → "Auto-Validation After Plan Creation") — the critical-questions interview run automatically once the plan file is written, for every mode except `--fast`. Suppressed by `--no-validate`. This is the `validate` subcommand, fired automatically.
- **Cook-time validation gate** (the "Validation gate" row above) — the `/t1k:review` (or equivalent) gate run *between phases during cook execution*. Advisory in default, recommended in `--hard`, mandatory in `--deep`. `--no-validate` does NOT affect this gate.

## Guards

- `--hard + --deep`: REFUSE. `--deep` is a superset of `--hard`; use `--deep` alone.
- `--fast + --deep`: REFUSE. Fast mode skips rigor; `--deep` mandates it. They are incompatible.
- `--tdd + --parallel`: REFUSE. TDD requires strict T→I→V ordering; parallel execution cannot preserve it.
- `--fast + --hard`: ALLOWED but discouraged — document the reason in the plan.
- `--no-validate`: suppresses the post-creation auto-validation interview. No-op under `--fast`. Under `--deep`, suppresses only the post-creation interview — the cook-time validation gate still runs.
- `--team-*` sub-flags without `--team`: WARN the user the sub-flag will be ignored, then proceed with plain mode (no team-shape sections).

## Test Cases

| Invocation | Expected Behavior |
|------------|-------------------|
| `/t1k:plan "feature X" --deep` | 3 researchers, per-phase scout, mandatory validation |
| `/t1k:plan "feature X" --hard --tdd` | 2 researchers, per-critical-phase scout, TDD sub-steps in every phase |
| `/t1k:plan "feature X" --deep --tdd` | 3 researchers, per-phase scout, mandatory validation, TDD sub-steps |
| `/t1k:plan "feature X" --hard --deep` | REFUSE — mutually exclusive |
| `/t1k:plan "feature X" --fast --deep` | REFUSE — mutually exclusive |
| `/t1k:plan "feature X" --team` | Emits team-shape sections; defaults: devs=auto, reviewers=1, researchers=0, debuggers=0 |
| `/t1k:plan "feature X" --team --deep` | Deep research + per-phase team shape + Plan-Fit Assessment Gate at cook time |
| `/t1k:plan "feature X" --team --team-devs 3 --team-reviewers 2` | 3 devs + 2 reviewers regardless of module count |
| `/t1k:plan "feature X" --team-devs 3` | WARN — `--team-devs` ignored without `--team`; proceeds in plain mode |
