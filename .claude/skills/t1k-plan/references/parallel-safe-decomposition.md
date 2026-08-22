---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Parallel-Safe Decomposition — Rationale & Details

Backs the "## Parallel-Safe Decomposition" section in `SKILL.md`. Source synthesis: `plans/reports/modular-for-parallel-260709-1510.md`.

## The unifying model

The seam you draw for **modularity** and the seam you draw for **parallelism** are the same seam, and it must pass both tests:

- **Calibration test** — the seam hides more complexity than its interface adds (Ousterhout *depth*), AND (≥3 real uses OR it's a stable domain / third-party edge — Rule of Three / AHA), AND only weak (name/type) connascence crosses it.
- **Parallel-fit test** — the seam yields an independently-ownable, independently-testable unit with a disjoint file set **and no shared declaration owned by a concurrent lane** (see "Disjointness is necessary, not sufficient" below).

**Order of operations:** find the stable domain seam first (calibration/contract-first), *then* parallelize across it. Parallelism is a benefit of a good seam, never a reason to draw one. Over-splitting to manufacture parallelism produces a distributed monolith — "independent" units that must all change together, where coordination overhead exceeds the independence gained.

This is the code-structure twin of D1's plan-side independence check: an edge crossing two parallel agents gets a contract; an edge inside one owner's slice does not.

## Empirical anchor

**27.7% of AI-agent PRs hit merge conflicts, and PR size/churn is the dominant predictor** (2-line diffs ~10% conflict rate → large diffs ~33%). Decomposition must bias toward many small, disjoint units with a machine-checkable test bar — this is Anthropic's own Opus-4.8 prescription: plan → isolated parallel units → verify against the test suite → staged merge.

## Slice by feature, never by layer

Feature slices own their files end-to-end → file-ownership islands N agents can build without collision. Layer-slicing (every agent touches the same shared service/controller file) is the #1 parallel anti-pattern — it manufactures the zero-overlap invariant's violation by construction.

## The SOTA triad

1. **Contract-first** — pin the shape (transport, field names, casing, enums, success/error envelope, null semantics) on every DAG edge crossing two agents, written verbatim into each agent's brief; point at one SSOT schema/types file where it exists rather than restating. See `rules/contract-first-integration.md`.
2. **Disjoint file-ownership + size cap** — the file→owner map is the parallel-safety proof **against write collisions only**; small units keep churn (and therefore conflict probability) low. It is not a proof of independence — see below.
3. **Worktree isolation + test bar + staged sequential merge** — lead pre-allocates one worktree/branch per agent (`rules/parallel-teammate-git-index-race.md`); each unit has an explicit pass/fail test command; integration happens via a staging branch → full-suite verify → sequential/rebased merge to main. Never merge N parallel branches straight to main concurrently.

## Disjointness is necessary, not sufficient — hoist shared declarations to the serial phase

**A file→owner map proves two lanes will not overwrite each other. It does not prove they can proceed
independently.** Lane B can own a wholly disjoint file set and still be blocked on a *type, schema,
migration, enum, or interface* that lane A is concurrently writing. The map reports the fan-out safe
because the files genuinely are disjoint; the coupling is in the declaration graph, which no
file-level check can see.

The failure is quiet in the worst way: each lane compiles or passes review in isolation, and the
mismatch surfaces only at integration, after every lane has reported success.

> **Rule — declaration hoisting.** Every artifact **declared by one lane and consumed by another**
> is hoisted into the **serial** phase that precedes fan-out. Parallel lanes write *implementations*;
> they never introduce *shared shapes*.

What this covers, by stack: ECS component structs · TypeScript `types.ts` / interfaces · protobuf and
GraphQL schemas · DB migrations and table shapes · shared enums and constants · API route
definitions · assembly/module manifests (`.asmdef`, `package.json` deps, `go.mod`) · DI registration
surfaces.

**Planner check, before publishing any wave:** for each type/schema in the fan-out, ask *"who declares
it, and does anyone in the same wave consume it?"* If yes, move the declaration into the serial phase
and leave the consumers where they are. This costs one file in the serial phase and removes an entire
class of integration failure.

**Distinguish from contract-first, which it completes.** Contract-first pins the *shape* in prose so
lanes agree. Declaration hoisting puts the *actual artifact* in the serial phase so lanes are not
waiting on each other to type it. A pinned contract with the declaration still inside a parallel lane
leaves every consumer blocked on that lane's schedule.

## Verification may not be parallelizable — name the serialization point

The triad's "explicit pass/fail test command per unit" silently assumes **every lane can run the
verifier concurrently**. On a single-instance toolchain that is false, and planning as if it were true
produces a wave whose success criteria are unreachable inside the wave that owns them.

Single-instance toolchains, non-exhaustively: a **Unity/Unreal editor** (one instance may hold a
project; compile, asset bake and play-mode all serialize) · a **shared dev database** where migrations
conflict · a **single emulator, simulator or physical device** · a **licence-limited tool** (one seat)
· **one staging environment** · a **hardware-in-the-loop rig**.

> **Rule — declare the verification topology with the wave plan.** State explicitly whether the
> verifier is *per-lane concurrent* or *globally serialized*. When it is serialized, the parallel unit
> is **authoring**, and verification becomes its own terminal, single-owner wave with real effort
> budgeted — not a formality appended to the last lane.

Two consequences planners get wrong:

- **A lane whose deliverable is a tool does not complete in its own wave.** Writing a generator,
  migration or fixture builder is the parallel unit; *running* it needs the serialized resource. Its
  success criteria belong to the verification wave, and its report must say *written and ready to
  run*, never *done*.
- **Order the serialized wave by dependency, not by lane number.** Whatever produces the artifacts
  other lanes verify against runs first inside it.

This composes with `rules/ai-velocity-batch-compile.md`: batch-implement blind, verify once. That rule
governs *edits*; this applies the same shape to *agents*.

## Guards against over-modularization (calibrated, NOT maximal)

- **Rule of Three / AHA** — no shared module for < 2–3 real current consumers; one speculative future consumer is not a consumer. Prefer duplication until the abstraction "screams."
- **Depth test** — a module's public interface must be narrower than the implementation it hides. Wide-interface/thin-body → collapse, don't ship.
- **Change-locality / connascence** — things that change together stay together; if two units would always appear in the same PR, they are one unit, not two parallel ones.

## Relationship to existing T1K assets

- **Reinforces** `rules/contract-first-integration.md` (now applied to first-party inter-slice seams, gated on "does this seam separate two parallel agents?"), `rules/parallel-teammate-git-index-race.md` (lead-allocated worktrees), `rules/library-third-party-decoupling.md` (day-one seam — the legitimate always-draw exception), `rules/coding-guidelines.md` §2 (YAGNI is the calibration guard).
- **Complements** the orchestration-rules-hardening plan diffs: those govern *when* to fan out agents; this governs *how* to structure code so the fan-out is conflict-free. D1's independence check and this seam test are the same test from two sides.
