---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# t1k-git — Incident Trail

Dated incident detail backing the rules in SKILL.md. The body carries the rule + one-line
why; this file records the originating incidents (progressive disclosure — loads on demand).

## Pre-commit lint gate — biome CI rounds lost (PR #79, 2026-04-21)

Over the span of PR #79 (2026-04-21), three CI rounds were lost to biome format violations
that `bun run lint` would have caught in 3 seconds locally. This established the pre-commit
lint gate rationale: a few seconds locally beats a full CI cycle plus a fix-up commit that
pollutes PR history.

## Wiki commit cross-reference miss (StickmanForge #8, 2026-06-04)

StickmanForge `#8` — wiki commit `8942519` carried `Refs ...#8` in its message but produced
zero cross-reference on the issue timeline (`commit_id: null` on every event); the issue had
to be closed manually. Wiki-repo commits do NOT honor closing/cross-ref keywords — only
main-repo commits/PRs do. Hence the "comment the wiki revision URL, or reference `#N` from a
main-repo commit/PR" guidance.

## Skill edits committed as `docs(...)` never released (2026-06-08)

theonekit-unity sat unreleased after three skill-body edits committed as
`docs(animation):` / `docs(tof):` (#206 / #195 / #208); the litmotion + tof skill
improvements never reached consumers until a `fix(animation,tof):` trigger commit forced the
release. Lesson: shipped `.claude/` content is `fix`/`feat`, never `docs` (no-bump).

## `feat(modules):` unrecognized — stuck release (2026-04-17 → 2026-04-18)

`theonekit-core` main was stuck at `modules-20260417-1213` for 3 commits
(2026-04-17 → 2026-04-18) because `feat(modules):` wasn't recognized (before
theonekit-release-action#6). Unsticking required force-moving the `v2` tag and a subsequent
core commit to trigger the fixed release pipeline.
