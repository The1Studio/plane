# Brainstorm Report — `plane-*` Fork Skill Set

**Date:** 2026-06-20 · **Branch:** company-main · **Status:** approved, → /t1k:plan

## Problem statement

The fork (`The1Studio/plane`, Plane CE) must survive monthly upstream rebases AND grow
custom features without leaking into core. Today the survival recipe lives only in
`docs/FORK.md` (human-run). Goal: a comprehensive **project-local** skill set that
operationalizes maintain + expand + sync + stay-compatible.

## Requirements (confirmed via AskUserQuestion)

- **Sync target:** upstream Plane CE, rebase-on-tags (the `docs/FORK.md` monthly cycle).
- **Home:** project-local `.claude/skills/` (plain `plane-*` names, not kit-shipped t1k-\*).
- **Coverage:** all 4 families — upstream sync, isolation guard, feature scaffold, downstream propagation.
- **Execution:** full-auto, EXCEPT 3 confirm gates (push / leak-abort / external issues).
- **Add-ons approved:** `plane-fork-doctor` + `.claude/rules/plane-fork-discipline.md`.

## Architecture — shared backbone + orchestrating skills (SSOT/DRY)

- `references/fork-convention.md` — SSOT mirror of `docs/FORK.md`: the 6 touch-points, core-model
  list (Issue/Page/Module/State…), new-app/new-package rule. Cited by every skill (no copy-paste drift).
- `scripts/plane-classify-path.cjs` — deterministic path classifier →
  `{category: core|touch-point|custom-app|custom-package, touchPointId}`. Reused by rebase
  (conflict classification) + audit (leak detection). Deterministic ⇒ script, not prose.

## The 6 touch-points (from docs/FORK.md, the only files allowed fork edits)

1. `INSTALLED_APPS` (settings) · 2. `urlpatterns` (core urls.py) · 3. `beat_schedule` (celery.py) ·
2. `base.py` LLM/Anthropic config · 5. `requirements/*` · 6. `extended.ts` (extendedRoutes seam).
   Conflict outside 1–6 = custom code leaked into core ⇒ ABORT + relocate.

## Skills (final set)

| Skill                    | Family              | Behavior                                                                                                                                                                                                                                      | Hard stop                            |
| ------------------------ | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `plane-rebase`           | upstream sync       | fetch tags → pick → rebase → classify each conflict (touch-point→auto via rerere/recipe; leak→abort) → `pnpm install && pnpm check` → `makemigrations --check` → tag `company-vX.Y.Z-N`                                                       | leak→abort; before `git push --tags` |
| `plane-isolation-audit`  | compatibility guard | scan tree/diff/PR for: edits outside touch-points, new columns on core models, edits to `plane/db/migrations/` or core `packages/*`/`@plane/*`, UI not via extendedRoutes. Mirrors company-main-ci.yml                                        | none (read-only)                     |
| `plane-scaffold-feature` | expansion           | new `plane/<name>/` app (models/urls/migrations/apps/serializers/views/tests) + optional `packages/<name>-ext/` + append-only touch-point wiring + CLAUDE.md "Custom features" line + queue propagation TODO. Clones the **workload** pattern | none (append-only)                   |
| `plane-propagate`        | downstream          | detect new endpoints/fields → open issues/PRs on plane-mcp-server, node/python SDKs, plane-claude-plugin, docs, developer-docs, (deploy/helm if new env)                                                                                      | before opening external issues       |
| `plane-fork-doctor`      | health              | aggregate: tags-behind-upstream, isolation status, migration check, rerere-cache health, propagation backlog                                                                                                                                  | none                                 |

Plus `.claude/rules/plane-fork-discipline.md` — auto-loaded project rule so ad-hoc edits also get guarded.

## Why this shape

- Reusability: one classifier + one convention ref → all skills share it; CI gate logic mirrored, not duplicated.
- Maintainability: 4 narrow skills > 1 mega-skill (easier routing, testing, activation).
- Testability: classifier is a pure CLI (unit-testable); audit asserts known-leak fixtures fail.

## Risks

- Full-auto conflict resolution: mitigated by the leak-abort gate + rerere (only replays _previously human-approved_ resolutions).
- Classifier drift from docs/FORK.md: mitigate by referencing FORK.md as SSOT + a doctor check that diffs the touch-point list.
- Downstream propagation = separate repos: skill opens issues/PRs there, never edits them from this repo's PR (per standing rule + kit-pr-workflow-boundary).

## Success criteria

- `plane-rebase` completes a real upstream-tag rebase, auto-resolving known touch-point conflicts, aborting on a seeded leak.
- `plane-isolation-audit` flags a seeded core-column violation locally (parity with CI gate).
- `plane-scaffold-feature` produces an app that passes `makemigrations --check` + `pnpm check` with zero touch-point conflicts.
- `plane-propagate` drafts correct sibling-repo issues for a new endpoint.

## Next step

Hand to `/t1k:plan` — phase order: (1) classifier + convention ref, (2) isolation-audit, (3) rebase,
(4) scaffold, (5) propagate, (6) doctor + rule.
