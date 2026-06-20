# Phase 3 — `plane-rebase` Skill

**Effort:** L · **Blocked by:** Phase 1 · **Parallel-safe with:** Phases 2, 4 · **CRITICAL PATH**
**Family:** upstream sync. Drives the `docs/FORK.md` §Rebase-on-tags monthly survival recipe.
**Two HARD-GATEs** (leak-abort, pre-push). Cite `rules/workflow-gates.md` for the HARD-GATE contract.

## Files owned (NEW)

| File                                                   | Purpose                                                                               |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| `skills/plane-rebase/SKILL.md`                         | Skillmark body: the rebase cycle, conflict classification, 2 HARD-GATEs.              |
| `skills/plane-rebase/references/rebase-recipe.md`      | Per-touch-point auto-resolve recipe table (mirrored from FORK.md §Conflict recovery). |
| `skills/plane-rebase/fixtures/seeded-leak-conflict.md` | Documented dry-run scenario: a conflict OUTSIDE touch-points 1–6 → MUST abort.        |

## The cycle (SKILL.md decision tree, mirroring FORK.md)

```
1. git fetch upstream --tags
2. git tag -l 'v*' | sort -V | tail -10   → pick target tag (e.g. v1.4.0)
3. git checkout company-main  (verify clean tree first)
4. git rebase <tag>
5. For each conflict (git diff --name-only --diff-filter=U):
     classify via plane-classify-path.cjs:
       touch-point → auto-resolve:
            - git rerere may already have replayed it (autoupdate=true) → git add + continue
            - else apply the per-touch-point recipe (references/rebase-recipe.md) → git add + continue
       core (leak) ──────────────► ⛔ HARD-GATE A: git rebase --abort. NEVER auto-resolve.
       (touch-point file deleted/renamed upstream) → also ABORT (FORK.md §recovery step 3)
6. pnpm install && pnpm check
7. cd apps/api && python manage.py makemigrations --check --dry-run && python manage.py check
8. ⛔ HARD-GATE B (pre-push): confirm before:
       git tag company-v<upstream>-<N> && git push origin company-main --tags
```

## HARD-GATEs (mandatory — cite `rules/workflow-gates.md`)

### `<HARD-GATE>` A — Leak-abort (NO override)

A rebase conflict in any file classified `core` (outside touch-points 1–6), OR a touch-point file
deleted/renamed upstream, MUST trigger `git rebase --abort`. The skill MUST NOT auto-resolve, force-add,
or `--continue` past it. Surface via `AskUserQuestion`: the leaked file + the relocation hint ("move to a
new app/package, then re-rebase"). **No override flag exists** — this is the load-bearing fork-survival rule.

### `<HARD-GATE>` B — Pre-push (override: explicit user "push")

After all checks pass, STOP before `git tag ... && git push ... --tags`. Surface the planned tag name,
the upstream tag adopted, the conflict-resolution summary, and the `pnpm check` + `makemigrations` results.
Push only on explicit user confirmation. Default override = none silent; user must say push.

### git rerere note

rerere is already enabled (`rerere.enabled true`, `rerere.autoupdate true` per FORK.md). rerere only
replays resolutions a human previously approved — it is safe and complementary to HARD-GATE A (rerere
never invents a resolution for a leak it has not seen approved).

## Activation

Trigger phrases: "rebase onto upstream tag", "adopt upstream Plane CE tag", "run the monthly rebase",
"sync fork to upstream", "rebase company-main onto vX.Y.Z".

## Steps

1. Author `SKILL.md` with the cycle + both `<HARD-GATE>` blocks (cite workflow-gates rule).
2. Author `rebase-recipe.md` mirroring FORK.md §Conflict-recovery per-touch-point table (1–6).
3. Document the seeded-leak dry-run scenario (a fake conflict in a core file) and the expected ABORT.

## Verify checks (dry-run / abort-path — no real upstream rebase in this phase)

```bash
# Abort-path proof: stage a synthetic out-of-bounds conflict, confirm classifier flags it core,
# confirm the documented skill response is `git rebase --abort` (not --continue).
node .claude/scripts/plane-classify-path.cjs apps/api/plane/db/models/issue.py   # → core → ABORT branch
# Touch-point auto-resolve path:
node .claude/scripts/plane-classify-path.cjs apps/api/plane/settings/common.py   # → touch-point 1 → recipe
git config --get rerere.enabled    # → true (precondition)
```

## Success criteria

- The skill's conflict-classification step delegates verdicts to `plane-classify-path.cjs` (no parallel logic).
- HARD-GATE A is documented as no-override and always-abort on any `core` conflict.
- HARD-GATE B is documented as always-stop-before-push.
- `rebase-recipe.md` covers all 6 touch-points with the FORK.md rebase-safe approach.
- Dry-run scenario shows a seeded core-file conflict resolves to ABORT, not continue.

## Risk Assessment

| Risk                                                                         | Likelihood (1-5) | Impact (1-5) | Score | Mitigation                                                                                                |
| ---------------------------------------------------------------------------- | ---------------- | ------------ | ----- | --------------------------------------------------------------------------------------------------------- |
| Auto-resolve a leak as a touch-point → corrupts core, compounds every rebase | 2                | 5            | 10    | HARD-GATE A (no override); classifier default-deny sends unknowns to `core` → abort.                      |
| Bad rebase pushed to origin/company-main                                     | 2                | 5            | 10    | HARD-GATE B: confirm before push; gate after pnpm check + makemigrations pass.                            |
| rerere replays a stale resolution after upstream context shift               | 2                | 3            | 6     | FORK.md step 3: touch-point renamed/deleted → abort; pnpm check + makemigrations catch breakage pre-push. |
| Skipping >2 upstream tags inflates conflict surface                          | 2                | 3            | 6     | Skill warns when target is >2 tags ahead of current `company-v*` (FORK.md cadence rule).                  |

## Timeline

| Item                    | Effort |
| ----------------------- | ------ |
| SKILL.md + 2 HARD-GATEs | L      |
| rebase-recipe.md        | S      |
| seeded-leak dry-run doc | S      |
| **Phase total**         | **L**  |
