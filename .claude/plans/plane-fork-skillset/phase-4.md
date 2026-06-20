# Phase 4 — `plane-scaffold-feature` Skill

**Effort:** M · **Blocked by:** Phase 1 · **Parallel-safe with:** Phases 2, 3 · **Blocks:** Phase 5
**Family:** expansion. Append-only — no HARD-GATE (never mutates core, only adds isolated files +
append-only touch-point lines). Clones the **workload** pattern (study, don't invent).

## Files owned (NEW)

| File                                                           | Purpose                                                                        |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `skills/plane-scaffold-feature/SKILL.md`                       | Skillmark body: clone-the-workload-pattern decision tree + append-only wiring. |
| `skills/plane-scaffold-feature/references/workload-pattern.md` | Annotated map of the reference implementation to clone.                        |

## Reference implementation to clone (verified in repo)

Backend app `apps/api/plane/workload/`:
`__init__.py`, `apps.py` (`WorkloadConfig`, `name="plane.workload"`, `label`, `verbose_name`),
`models.py`, `serializers.py`, `views.py`, `urls.py` (+ `api_urls.py`/`api_views.py` for public `/api/v1/`),
`service.py`/`aggregation.py`, `migrations/`, `tests/`.

Frontend package `packages/workload-ext/`:
`package.json` (`@plane/workload-ext`, `workspace:*` deps, tsdown build), `tsconfig.json`, `src/`, `dist/`.

## Scaffold output (decision tree in SKILL.md)

```
Inputs: feature name <name>, needs-frontend? (y/n)
1. Backend: create apps/api/plane/<name>/ cloning workload structure
     (apps.py with name="plane.<name>", own migrations/, urls.py, models.py, serializers.py,
      views.py, tests/).  NO new columns on core models — new tables only (FORK.md DB rule).
2. (optional) Frontend: create packages/<name>-ext/ cloning workload-ext
     (package.json @plane/<name>-ext, workspace:* deps, tsconfig, src/).
3. Append-only touch-point wiring (verify each via plane-classify-path.cjs = touch-point):
     - TP1 common.py INSTALLED_APPS: append "plane.<name>", in the in-house block
     - TP2 urls.py:               append path("api/<name>/", include("plane.<name>.urls")),
     - TP6 extended.ts (if FE):   append a route(...) entry to extendedRoutes
4. Add a one-line entry under CLAUDE.md "Custom features (fork-owned)".
5. Queue a propagation TODO (consumed by plane-propagate, Phase 5):
     write/append to .claude/plane-propagation-queue.md — feature name, new endpoints, new fields.
6. Verify: makemigrations --check + pnpm check.
```

> **Append-only discipline:** every touch-point edit is an append (never a modify/delete of an existing
> line) so it survives rebase per FORK.md. The skill runs each edited file through the Phase-1 classifier
> to confirm it is a touch-point (not a leak) before writing.

## Activation

Trigger phrases: "scaffold a fork feature", "new Plane app", "add an isolated Django app",
"create a new fork feature like workload", "scaffold backend app + frontend package".

## Steps

1. Author `workload-pattern.md` — annotate each workload file's role (what to clone, what to rename).
2. Author `SKILL.md` with the decision tree, the append-only wiring rules, the CLAUDE.md update step,
   and the propagation-queue write.
3. Document the verify gate.

## Verify checks

```bash
# After a scaffold run for a sample feature <name>:
cd apps/api && python manage.py check                                  # app loads
cd apps/api && python manage.py makemigrations --check --dry-run       # migrations complete
pnpm install --frozen-lockfile && pnpm check                           # FE type-check (if package added)
node .claude/scripts/plane-classify-path.cjs apps/api/plane/<name>/models.py   # → custom-app
# touch-point edits classify as touch-point, NOT core:
node .claude/scripts/plane-classify-path.cjs apps/api/plane/settings/common.py # → touch-point 1
```

## Success criteria

- A scaffolded sample app passes `manage.py check` + `makemigrations --check` with ZERO touch-point conflicts.
- Touch-point edits are append-only and classify as `touch-point` (verified via Phase-1 classifier).
- CLAUDE.md gains a "Custom features" line; a propagation TODO is queued for Phase 5.
- Optional frontend package passes `pnpm check`.

## Risk Assessment

| Risk                                                              | Likelihood (1-5) | Impact (1-5) | Score | Mitigation                                                                                                     |
| ----------------------------------------------------------------- | ---------------- | ------------ | ----- | -------------------------------------------------------------------------------------------------------------- |
| Scaffold adds a column on a core model (violates DB rule)         | 2                | 4            | 8     | Skill enforces new-tables-only; clones workload (which uses its own tables); makemigrations gate.              |
| Touch-point edit is a modify (not append) → rebase conflict later | 2                | 3            | 6     | Append-only rule + classifier check that edits land in touch-point files only.                                 |
| Stale clone drift (workload pattern changes, skill doesn't)       | 2                | 2            | 4     | `workload-pattern.md` points at live `apps/api/plane/workload/`; skill reads the live tree, not a frozen copy. |
| Propagation TODO never written → Phase 5 has nothing to read      | 2                | 3            | 6     | Step 5 is a mandatory skill step; doctor (Phase 6) surfaces an empty/missing queue as backlog signal.          |

## Timeline

| Item                | Effort |
| ------------------- | ------ |
| workload-pattern.md | S      |
| SKILL.md body       | M      |
| **Phase total**     | **M**  |
