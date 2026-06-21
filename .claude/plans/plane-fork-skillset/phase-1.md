# Phase 1 — Path Classifier + Convention Reference

**Effort:** M · **Blocks:** Phases 2, 3, 6 · **Blocked by:** none
**Goal:** the shared backbone — one deterministic classifier + one SSOT convention mirror that every
later skill cites. Per `ai-driven-design.md`: deterministic path→category is a **script**, not prose.

## Files owned (all NEW, all under `.claude/`)

| File                                           | Purpose                                                                                              |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `scripts/plane-classify-path.cjs`              | CLI: file path → `{category, touchPointId, reason}`. SSOT for "may this file be edited in the fork." |
| `scripts/test/plane-classify-path.test.cjs`    | Node unit tests (table-driven, zero deps — `node:test` + `node:assert`).                             |
| `skills/_shared/references/fork-convention.md` | Mirror/pointer to `docs/FORK.md`: the 6 touch-points + core-model list. Cited by every skill.        |

## Classifier contract

```
Usage: node scripts/plane-classify-path.cjs <path> [<path> ...]
Output (JSON, one object per input path):
  { "path": "...",
    "category": "core" | "touch-point" | "custom-app" | "custom-package",
    "touchPointId": 1..6 | null,
    "reason": "<one-line>" }
Exit 0 always (classification is not a verdict); category drives caller policy.
```

### Classification rules (derived from `docs/FORK.md` §Isolation convention, mirrored in fork-convention.md)

1. **touch-point** — path matches one of the 6 SSOT entries (set `touchPointId` 1–6):
   1. `apps/api/plane/settings/common.py`
   2. `apps/api/plane/urls.py`
   3. `apps/api/plane/celery.py`
   4. `apps/api/plane/app/views/external/base.py`
   5. `apps/api/requirements/base.txt`, `apps/api/Dockerfile.api`
   6. `apps/web/app/routes/extended.ts`, `apps/web/package.json`
2. **custom-app** — under `apps/api/plane/<app>/` where `<app>` ∈ the fork-owned app set
   (`ai_ext`, `clickup_migrate`, `workload`, + future apps). Source the app set from the
   `INSTALLED_APPS` fork block, not a hardcoded list (data-driven — see `code-conventions.md`).
3. **custom-package** — under `packages/<name>-ext/` (the fork frontend-package convention).
4. **core** — everything else, INCLUDING `apps/api/plane/db/migrations/` and `@plane/*` packages
   (explicitly never-edit). This is the default/deny category.

> **Data-driven mandate:** the touch-point list + fork-app set live in `fork-convention.md` (or are
> read from the live tree). Deleting an inline static map must not change behavior — if it does,
> you hardcoded. The classifier reads the touch-point table; it does not embed it as a frozen literal
> beyond a single parsed source.

### `fork-convention.md` content

- A 2-line header pointing to `docs/FORK.md` as the authoritative SSOT ("this file mirrors; on conflict,
  FORK.md wins").
- The 6-touch-point table (file → touchPointId → rebase-safe approach) extracted from FORK.md §Isolation.
- The core-model list: `Issue, Page, Module, State, Intake, Asset` + the "no new columns" rule.
- The new-app / new-package rule. NO logic beyond what FORK.md states.

## Steps

1. Write `fork-convention.md` extracting the FORK.md §Isolation tables verbatim (mirror, attribute SSOT).
2. Write `plane-classify-path.cjs` — parse argv, classify each path per rules above, print JSON array.
   Read the touch-point table + fork-app set from `fork-convention.md` (or glob `INSTALLED_APPS`).
3. Write the unit test table covering: all 6 touch-points (each → correct `touchPointId`); a known core
   file (`apps/api/plane/db/models/issue.py` → core); `apps/api/plane/db/migrations/0001_initial.py`
   → core; `apps/api/plane/workload/models.py` → custom-app; `packages/workload-ext/src/index.ts`
   → custom-package; an out-of-tree path → core (default-deny).

## Verify checks

```bash
node .claude/scripts/test/plane-classify-path.test.cjs        # all assertions pass, exit 0
node .claude/scripts/plane-classify-path.cjs apps/api/plane/urls.py    # → touch-point, touchPointId 2
node .claude/scripts/plane-classify-path.cjs apps/api/plane/db/models/issue.py  # → core
```

## Success criteria

- Test suite passes with zero failures; covers every category + all 6 touch-points + the two never-edit
  core cases (db/migrations, @plane/\*).
- `fork-convention.md` contains zero classification logic absent from `docs/FORK.md` (pure mirror).
- Classifier has zero npm dependencies (uses only `node:` builtins).

## Risk Assessment

| Risk                                                       | Likelihood (1-5) | Impact (1-5) | Score | Mitigation                                                                                                       |
| ---------------------------------------------------------- | ---------------- | ------------ | ----- | ---------------------------------------------------------------------------------------------------------------- |
| Hardcoded fork-app list goes stale when a new app is added | 3                | 3            | 9     | Source the app set from `INSTALLED_APPS` / fork-convention.md, not an inline literal. Doctor (Phase 6) diffs it. |
| `db/migrations` or `@plane/*` misclassified as editable    | 1                | 5            | 5     | Explicit core default + dedicated test cases for both.                                                           |
| Convention mirror drifts from FORK.md                      | 2                | 4            | 8     | Header declares FORK.md SSOT; Phase 6 doctor diffs touch-point list.                                             |

## Timeline

| Item                      | Effort |
| ------------------------- | ------ |
| fork-convention.md mirror | S      |
| classifier script         | M      |
| unit test table           | S      |
| **Phase total**           | **M**  |
