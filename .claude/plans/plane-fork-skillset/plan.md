# Plan: `plane-*` Fork Skill Set

**Created:** 2026-06-20 21:10 · **Branch:** `plan/plane-fork-skillset` (off `company-main`)
**Source design:** `.claude/plans/reports/plane-fork-skillset-brainstorm.md` (approved)
**SSOT convention:** `docs/FORK.md` (6 touch-points + core-model list — mirror, never fork)

A project-local skill set that operationalizes maintaining + expanding `The1Studio/plane`
(Plane CE fork) while staying synced/compatible with upstream. All deliverables are NEW,
project-local under `.claude/`, named plain `plane-*` (NOT kit-shipped `t1k-*`).

---

## Naming + Activation Mechanism (verified)

These are **project-local** skills, NOT TheOneKit kit skills. Consequences carried into every phase:

- **NO** sync-back, **NO** `/t1k:issue`, **NO** module registry / `t1k-modules.json` edits, **NO**
  activation-fragment registration. None of the kit-propagation rules apply to these files.
- **Naming:** plain `plane-<slug>` directory + `name: plane:<slug>` (or `plane-<slug>`) in
  SKILL.md frontmatter. Verified against existing project-local skills under `.claude/skills/`
  (e.g. `t1k-web-core-backend-development/SKILL.md`): a project-local skill is just a
  `.claude/skills/<dir>/SKILL.md` file with Skillmark frontmatter — Claude Code auto-discovers it
  from the project `.claude/skills/` tree. No central registry entry is required for discovery.
- **Invocation:** discovered + activated by the `description` + `keywords` frontmatter
  (keyword/context auto-activation), or invoked explicitly by name via the Skill tool. Each SKILL.md
  carries an `## Activation` block listing the trigger phrases (e.g. "rebase onto upstream tag",
  "audit fork isolation", "scaffold a fork feature").

---

## Phases

| #   | Phase                                    | Scope / files owned                                                                                                            | Effort |
| --- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------ |
| 1   | Classifier + convention reference        | `scripts/plane-classify-path.cjs`, `scripts/test/plane-classify-path.test.cjs`, `skills/_shared/references/fork-convention.md` | M      |
| 2   | `plane-isolation-audit` skill            | `skills/plane-isolation-audit/SKILL.md` + fixtures                                                                             | M      |
| 3   | `plane-rebase` skill                     | `skills/plane-rebase/SKILL.md` + abort-path test                                                                               | L      |
| 4   | `plane-scaffold-feature` skill           | `skills/plane-scaffold-feature/SKILL.md`                                                                                       | M      |
| 5   | `plane-propagate` skill                  | `skills/plane-propagate/SKILL.md`                                                                                              | S      |
| 6   | `plane-fork-doctor` skill + project rule | `skills/plane-fork-doctor/SKILL.md`, `rules/plane-fork-discipline.md`                                                          | M      |

All paths relative to `/mnt/Work/1M/15. Plane/plane/.claude/`.

Per-phase detail: `phase-1.md` … `phase-6.md`.

---

## Feasibility

- **Reuse check:**
  - Path classifier — **NEW**. No existing deterministic classifier in repo.
  - Convention reference — **mirror** of existing `docs/FORK.md` (no new logic; pointer + extracted tables).
  - Skills — **NEW**, but `plane-scaffold-feature` clones the existing `apps/api/plane/workload/`
    - `packages/workload-ext/` pattern (study, don't invent).
  - CI parity — `plane-isolation-audit` + `plane-rebase` mirror gates already in
    `.github/workflows/company-main-ci.yml` (`manage.py check`, `makemigrations --check`, `pnpm check`).
- **Complexity:** moderate. The only genuinely complex piece is `plane-rebase` (git rerere + conflict
  classification + 2 of the 3 confirm gates). Everything else is read-only scanning or append-only scaffolding.

---

## Dependencies

- **Phase 1 blocks 2, 3, 6** — classifier script + `fork-convention.md` are the shared backbone
  consumed by audit (leak detection), rebase (conflict classification), and doctor (drift check).
- **Phase 4 blocks 5** — `plane-propagate` consumes the propagation TODO that `plane-scaffold-feature`
  queues; build scaffold first so propagate has a real producer to read from.
- **Phases 2, 3, 4 are parallel-safe after Phase 1** — disjoint file ownership
  (`plane-isolation-audit/`, `plane-rebase/`, `plane-scaffold-feature/` are separate dirs).
- **Phase 6 blocked by 1–5** — doctor aggregates signals the other skills define (isolation status,
  rebase tags-behind, propagation backlog); build last.

### Critical path

`Phase 1 → Phase 3` (classifier → rebase, the longest single phase). Phases 2 + 4 run alongside 3.
Phase 5 follows 4; Phase 6 closes.

---

## Risk Assessment (project-level; per-phase tables in `phase-N.md`)

| Risk                                                                        | Likelihood (1-5) | Impact (1-5) | Score | Mitigation                                                                                                                                                              |
| --------------------------------------------------------------------------- | ---------------- | ------------ | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full-auto rebase auto-resolves a leak as if a touch-point → corrupts core   | 2                | 5            | 10    | HARD-GATE: any conflict OUTSIDE touch-points 1–6 → `git rebase --abort`, never auto-resolve (Phase 3). rerere only replays human-approved resolutions.                  |
| Classifier drifts from `docs/FORK.md` → audit/rebase misjudge files         | 3                | 4            | 12    | Classifier reads touch-point paths from `fork-convention.md`-mirrored table; `plane-fork-doctor` diffs the live FORK.md touch-point list vs classifier table (Phase 6). |
| Audit logic diverges from CI gate → local "clean" but CI fails              | 3                | 3            | 9     | Phase 2 fixtures assert parity with `company-main-ci.yml` checks; audit cites the exact CI commands it mirrors.                                                         |
| `plane-propagate` edits a sibling repo from this repo's PR (rule violation) | 2                | 4            | 8     | HARD-GATE + `kit-pr-workflow-boundary`: background issue-open only, report URL, stop. Never clones/edits sibling.                                                       |
| Auto-push of a bad rebase to `origin/company-main`                          | 2                | 5            | 10    | HARD-GATE: confirm before `git push --tags` (Phase 3).                                                                                                                  |
| Scaffold breaks `makemigrations --check` / `pnpm check`                     | 2                | 3            | 6     | Phase 4 success criterion runs both checks; clones a known-passing workload app.                                                                                        |

No score ≥ 15. The two score-10 rebase risks are fully gated by mandatory HARD-GATEs, not mitigated by judgment.

---

## Timeline

| Phase                           | Effort               | Notes                                                             |
| ------------------------------- | -------------------- | ----------------------------------------------------------------- |
| 1 — classifier + convention ref | M                    | Blocks 2/3/6. Pure-CLI + unit tests.                              |
| 2 — isolation-audit             | M                    | After 1. Parallel-safe with 3/4.                                  |
| 3 — rebase                      | L                    | After 1. Critical path. 2 HARD-GATEs.                             |
| 4 — scaffold-feature            | M                    | After 1. Parallel-safe. Blocks 5.                                 |
| 5 — propagate                   | S                    | After 4. 1 HARD-GATE.                                             |
| 6 — doctor + rule               | M                    | After 1–5. Aggregator + auto-loaded rule.                         |
| **Total**                       | **~3 L-equivalents** | Critical path: 1 → 3. Parallelizable: {2,3,4} concurrent after 1. |

---

## Behavioral checklist (pre-handoff)

- [x] Data flows traced — classifier output (`{category, touchPointId}`) consumed by audit/rebase/doctor.
- [x] Dependency graph — blockers explicit; {2,3,4} labeled parallel-safe; critical path 1→3.
- [x] Risk assessment — scored; no ≥15; the two 10s are HARD-GATE-mitigated.
- [x] Backwards compatibility — all additive (new files); the 3 confirm gates preserved as HARD-GATEs.
- [x] Test matrix — Phase 1 unit tests; Phase 2 fixture parity; Phase 3 abort-path dry-run.
- [x] Rollback — every phase adds isolated files; revert = delete the new dir/file. No core edits.
- [x] File ownership — each phase owns disjoint dirs; no shared-file sequencing conflicts.
- [x] Success criteria — objective commands per phase (`node test`, seeded-fixture flag, dry-run abort).
