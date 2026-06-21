# Phase 2 — `plane-isolation-audit` Skill

**Effort:** M · **Blocked by:** Phase 1 · **Parallel-safe with:** Phases 3, 4
**Family:** compatibility guard. **Read-only** (no HARD-GATE — never mutates).
**Goal:** scan tree / diff / PR for fork-convention violations, mirroring the CI gates in
`.github/workflows/company-main-ci.yml` so a violation is caught locally before it reaches CI.

## Files owned (NEW)

| File                                                                 | Purpose                                                                           |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `skills/plane-isolation-audit/SKILL.md`                              | Skillmark skill body + decision-tree + activation.                                |
| `skills/plane-isolation-audit/fixtures/leak-core-column.diff`        | Seeded fixture: a fake new column on a core model. MUST be flagged.               |
| `skills/plane-isolation-audit/fixtures/leak-outside-touchpoint.diff` | Seeded fixture: an edit to a core file outside touch-points 1–6. MUST be flagged. |
| `skills/plane-isolation-audit/fixtures/clean.diff`                   | A valid append-only touch-point edit. MUST pass.                                  |

## What the audit checks (parity with `company-main-ci.yml`)

1. **Edits outside touch-points** — run `plane-classify-path.cjs` over `git diff --name-only`
   (or PR file list); any changed file classified `core` = violation.
2. **New columns on core models** — grep the diff for added fields on `Issue/Page/Module/State/Intake/Asset`
   model classes (the no-new-columns rule). Mirrors the intent of the CI `makemigrations --check` gate.
3. **Edits to `plane/db/migrations/` or `@plane/*`** — flagged via classifier (both → core).
4. **UI not via extendedRoutes** — new `apps/web/app/routes/` edits outside `extended.ts` = violation.
5. **CI-command parity advisory** — surface the exact CI checks it mirrors:
   `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `pnpm check`.

## Decision tree (in SKILL.md)

```
Input scope?
 ├─ working tree   → git diff --name-only HEAD
 ├─ a commit range → git diff --name-only <base>..<head>
 └─ a PR number    → gh pr diff <N> --name-only
For each changed file → classify via plane-classify-path.cjs:
  core           → VIOLATION (report file + reason + relocation hint: "move to a new app/package")
  touch-point    → OK, but verify edit is APPEND-ONLY (warn if a touch-point line was deleted/modified)
  custom-app/pkg → OK
Then content scans: core-model column add? non-extended.ts route add?
Output: a violation table (file | category | rule | fix) + overall PASS/FAIL.
```

## Activation (SKILL.md `## Activation` block)

Trigger phrases: "audit fork isolation", "check isolation", "did I leak into core",
"will this pass company-main CI", "isolation audit", "pre-rebase isolation check".

## Steps

1. Author `SKILL.md` (Skillmark frontmatter: `name: plane:isolation-audit`, description, keywords,
   `## When to Use`, `## Activation`, `## Decision Tree`, `## CI Parity`, `## Output`).
2. Create the 3 fixture diffs.
3. Document the verify procedure (run audit against each fixture).

## Verify checks

```bash
# leak fixtures MUST be flagged FAIL:
git apply --check skills/plane-isolation-audit/fixtures/leak-core-column.diff && \
  node .claude/scripts/plane-classify-path.cjs <files-in-diff>   # → core → VIOLATION
# clean fixture MUST PASS (all changed files touch-point/custom)
```

(The skill drives `plane-classify-path.cjs`; the fixtures prove the seeded leaks are caught and the
clean diff passes — parity with the CI gate.)

## Success criteria

- `leak-core-column.diff` and `leak-outside-touchpoint.diff` both produce a FAIL with the offending
  file named + a relocation hint.
- `clean.diff` produces PASS.
- The skill explicitly lists the 3 CI commands it mirrors (no drift between local audit and CI).

## Risk Assessment

| Risk                                                    | Likelihood (1-5) | Impact (1-5) | Score | Mitigation                                                                                                        |
| ------------------------------------------------------- | ---------------- | ------------ | ----- | ----------------------------------------------------------------------------------------------------------------- |
| Audit passes a violation CI would catch (false-clean)   | 3                | 4            | 12    | Fixture parity tests; audit delegates path verdicts to the Phase-1 classifier (single source).                    |
| Core-model column grep misses an add (regex blind spot) | 3                | 3            | 9     | Back-stop with the `makemigrations --check` advisory; flag ANY core-file edit as violation regardless of content. |
| False positive on a legitimate touch-point append       | 2                | 2            | 4     | Touch-point edits pass by default; only deleted/modified (non-append) touch-point lines warn.                     |

## Timeline

| Item            | Effort |
| --------------- | ------ |
| SKILL.md body   | M      |
| 3 fixtures      | S      |
| **Phase total** | **M**  |
