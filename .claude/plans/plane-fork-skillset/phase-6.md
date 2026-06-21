# Phase 6 — `plane-fork-doctor` Skill + `plane-fork-discipline` Rule

**Effort:** M · **Blocked by:** Phases 1–5 · **Blocks:** none
**Family:** health aggregator + auto-loaded project rule. Read-only doctor; the rule guards ad-hoc edits.
Build last — it aggregates signals the other skills define.

## Files owned (NEW)

| File                                | Purpose                                                             |
| ----------------------------------- | ------------------------------------------------------------------- |
| `skills/plane-fork-doctor/SKILL.md` | Skillmark body: aggregate fork health into one report. Read-only.   |
| `rules/plane-fork-discipline.md`    | Auto-loaded project rule reminding the convention for ad-hoc edits. |

## Doctor checks (aggregate — each reuses an existing signal)

| Check                    | Source / command                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------------------- |
| Tags-behind-upstream     | `git fetch upstream --tags` + compare latest `v*` vs current `company-v*` (FORK.md cadence; warn if >2 behind). |
| Isolation status         | run the `plane-isolation-audit` logic over the working tree (Phase 2).                                          |
| Migration check          | `cd apps/api && python manage.py makemigrations --check --dry-run`.                                             |
| Django system check      | `cd apps/api && python manage.py check`.                                                                        |
| rerere-cache health      | `git config --get rerere.enabled` = true + `.git/rr-cache/` present/non-pruned (FORK.md).                       |
| Classifier↔FORK.md drift | diff the touch-point list in `fork-convention.md` (Phase 1) vs `docs/FORK.md` §Isolation table.                 |
| Propagation backlog      | count open entries in `.claude/plane-propagation-queue.md` (Phase 4/5).                                         |

Output: a single health table (check | status | detail) + an overall GREEN/YELLOW/RED.

## `plane-fork-discipline.md` rule (auto-loaded, project-local)

Mirrors `rules/*.md` format. Content (reminds for ANY ad-hoc edit, not just skill-driven):

- Backend customization = NEW Django app (own `migrations/`, `urls.py`, `models.py`). Never edit
  `plane/db/migrations/` or `@plane/*`.
- No new columns on core models (`Issue/Page/Module/State/Intake/Asset`) — new tables only.
- Frontend customization = NEW `packages/<name>-ext/`; mount UI via `extended.ts` (touch-point 6).
- Only the 6 touch-points may carry fork edits; a conflict outside them = a leak → relocate.
- After any rebase: `makemigrations --check` (CI gate `company-main-ci.yml`).
- Every new feature → propagate downstream (MCP/SDK/docs) per CLAUDE.md standing rule.
- Points at `docs/FORK.md` as SSOT and the `plane-*` skills as the operational tools.

## Activation

Doctor trigger phrases: "fork health", "fork doctor", "is the fork healthy", "check fork status",
"tags behind upstream", "fork health report".
Rule: auto-loaded every session (no activation needed — it lives in `.claude/rules/`).

## Steps

1. Author `plane-fork-discipline.md` (concise, cites `docs/FORK.md` SSOT; mirrors rule format).
2. Author `plane-fork-doctor/SKILL.md` aggregating the 7 checks above, each delegating to an
   existing command/skill (no new logic — pure aggregation).

## Verify checks

```bash
# Doctor produces a health table touching all 7 checks without erroring:
git config --get rerere.enabled                                   # rerere check input
cd apps/api && python manage.py makemigrations --check --dry-run   # migration check input
node .claude/scripts/plane-classify-path.cjs apps/api/plane/urls.py # classifier reachable
ls .claude/rules/plane-fork-discipline.md                          # rule file present (auto-loads)
```

## Success criteria

- Doctor runs all 7 checks and emits one GREEN/YELLOW/RED report; each check delegates to an existing
  signal (no duplicated logic — DRY).
- The drift check actually diffs `fork-convention.md` touch-points vs `docs/FORK.md` (catches Phase-1 drift risk).
- `plane-fork-discipline.md` is in `.claude/rules/` and auto-loads (verified by presence + format match
  with an existing `rules/*.md`).

## Risk Assessment

| Risk                                                                   | Likelihood (1-5) | Impact (1-5) | Score | Mitigation                                                                                               |
| ---------------------------------------------------------------------- | ---------------- | ------------ | ----- | -------------------------------------------------------------------------------------------------------- |
| Doctor duplicates audit/rebase logic instead of delegating (DRY break) | 3                | 2            | 6     | Each check delegates to an existing command/skill; doctor only aggregates + formats.                     |
| Drift check passes while convention silently diverged                  | 2                | 4            | 8     | Drift check is a literal diff of touch-point lists FORK.md vs fork-convention.md; fails on any mismatch. |
| Rule too verbose → ignored, or duplicates FORK.md                      | 2                | 2            | 4     | Keep concise; cite FORK.md as SSOT; mirror existing `rules/*.md` brevity.                                |

## Timeline

| Item                          | Effort |
| ----------------------------- | ------ |
| plane-fork-discipline.md rule | S      |
| plane-fork-doctor SKILL.md    | M      |
| **Phase total**               | **M**  |
