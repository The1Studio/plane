# Phase 1 — Dual-target CI, neuter upstream workflows, sweep live docs

**Effort:** M (~3h) · **Depends on:** nothing · **Delivers:** one PR merged into `company-main`

Everything in this phase lands _before_ any branch is renamed or deleted. Nothing here
assumes `master` exists yet.

## Why dual-target instead of a straight swap

A straight `company-main` → `master` swap in the trigger lists leaves a window where the
branch is still called `company-main` and every workflow listens for `master`: the fork CI
gate and the production deploy are both dead for the duration. Listing **both** names means
no workflow is ever pointed at a branch that does not exist. Phase 4 removes the
`company-main` half once the rename has landed.

## Files owned by this phase

### A. Fork-owned workflows — dual-target

| File                                        | Edit                                                                                                                                                                  |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.github/workflows/company-main-ci.yml`     | `push.branches` (line ~14) and `pull_request.branches` (line ~17): `[company-main]` → `[company-main, master]`                                                        |
| `.github/workflows/deploy-company-main.yml` | `push.branches` (line 5): `[company-main]` → `[company-main, master]`                                                                                                 |
| `.github/workflows/upstream-sync-check.yml` | `git checkout company-main` → `git checkout master` at lines ~117 and ~135 (both inside heredocs that render a rebase recipe into a job summary and a tracking issue) |

Leave `concurrency.group: deploy-company-main` alone — it is an arbitrary lock name, not a
branch reference, and changing it during the transition would let two deploys run at once.

### B. Upstream-owned workflows — delete one, neuter the other

Both are upstream Plane files outside FORK.md's seven touch-points, so both create a
rebase-conflict surface — the cost D4 accepted. Each needs a row in FORK.md's core-edit
exception table (see C) recording what was done and why no upstream seam exists.

| File                                  | Action                                                                                     | Why                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.github/workflows/check-version.yml` | **Delete the file.**                                                                       | Its whole job is to fail any PR whose root `package.json` version matches the base branch's — correct for upstream's release flow, wrong for ours. Keeping it would make a version bump mandatory on every PR into `master`, including docs-only ones, and our `version` field is upstream's (`1.3.1`, overwritten by every rebase-on-tags) rather than a number the fork owns. Decided: remove it outright rather than leave a dormant file. |
| `.github/workflows/codeql.yml`        | Remove `"master"` from both branch lists (lines 6 and 8), leaving `["preview", "canary"]`. | Both remaining names are branches this repo will not have, so the workflow goes fully dormant instead of newly firing on every push to production. Not deleted — a future decision may want scanning back, and re-adding a branch name is a one-line change.                                                                                                                                                                                  |

The deletion of `check-version.yml` will conflict on any future rebase where upstream touches
that file. That is expected and is resolved by re-deleting it; note this explicitly in the
FORK.md exception row so the next person rebasing does not "restore" it by reflex.

### C. `docs/FORK.md` — the highest-value edit in the change (24 refs)

Three edits matter more than the mechanical find-and-replace:

1. **Branch-model table (lines ~12–16).** Rename the `company-main` row to `master`. **Delete**
   the `` `preview`, `master` — Upstream tracking branches `` row outright; both branches are
   being removed, and for `master` the claim was never true (verified: `upstream/master` is not
   an ancestor of `origin/master`).
2. **Line ~20 rule.** `` `company-main` is derived from an upstream **tag**, never from
`preview` or `master` `` → name the remotes explicitly: `never from `upstream/preview`or`upstream/master``.
3. **Line ~35, the rebase rule.** ``Never rebase onto `preview`/`master` (moving targets…)``
   → `` Never rebase onto `upstream/preview` / `upstream/master` ``. Add a short warning block
   immediately below it:

   > **Name collision.** Our production branch is `master`, and upstream's _release_ branch is
   > also called `master` (`upstream/master`, last seen at `v1.4.2`). A bare `master` in any
   > command resolves to **ours**. Always remote-qualify when you mean upstream's.

Then sweep the remaining refs: lines ~44–45 and ~64 (`git checkout company-main`,
`git push origin company-main --tags`), ~109 and ~121 (rebase-abort recovery text), ~409,
~643, ~970, ~1089, ~1100. Lines ~292 and ~299 cite `company-main@6c2c8fb` — that is a
historical SHA reference, so rewrite the branch name but keep the SHA.

Finally add the two Section-B rows to the core-edit exception table (near lines ~1055–1056,
where `company-main-ci.yml` and `deploy-company-main.yml` are already listed).

### D. Live rules, skills, and scripts

| File                                                           | Refs | Note                                                                                          |
| -------------------------------------------------------------- | ---- | --------------------------------------------------------------------------------------------- |
| `.claude/rules/plane-fork-discipline.md`                       | 2    | Auto-loaded every session — stale text here misleads every future turn                        |
| `.claude/skills/plane-rebase/SKILL.md`                         | 10   | Highest count; apply the same `upstream/`-qualification as FORK.md item 3                     |
| `.claude/skills/plane-rebase/fixtures/seeded-leak-conflict.md` | 2    | Test fixture                                                                                  |
| `.claude/skills/plane-isolation-audit/SKILL.md`                | 6    |                                                                                               |
| `.claude/skills/plane-fork-doctor/SKILL.md`                    | 3    |                                                                                               |
| `.claude/skills/plane-scaffold-feature/SKILL.md`               | 1    |                                                                                               |
| `.claude/skills/_shared/references/fork-convention.md`         | 3    | Also carries the `forkApps` registry CI reads                                                 |
| `CONTRIBUTING.md`                                              | 2    |                                                                                               |
| `deployments/selfhost/deploy.sh`                               | 3    | Comments only (lines 3, 4, 49) — no executable reference                                      |
| `deployments/selfhost/notify-discord.sh`                       | 1    | Comment only (line 4)                                                                         |
| `apps/api/plane/github_ext/tests/test_issue_sync.py`           | 1    | Check whether it is a comment or a literal; a literal branch name in an assertion must change |
| `apps/api/requirements/base.txt`                               | 1    | Almost certainly a comment; confirm before editing                                            |
| `docs/clickup-migration-status.md`                             | 1    |                                                                                               |

Before deleting `preview` in Phase 3, grep the skills for a consumer:

```bash
grep -rn "origin/preview\|refs/heads/preview" .claude/ docs/ deployments/
```

Any hit is a Phase 1 fix, not a Phase 3 surprise.

### E. Explicitly NOT swept

`plans/**`, `.claude/plans/**`, `.claude/handoffs/**` — roughly 40 refs across historical plan
and handoff files. They record what was true when written. Rewriting them falsifies the record
and produces a large, unreviewable diff that hides the real changes.

## Verification

```bash
python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"
grep -rn "company-main" --exclude-dir=.git --exclude-dir=node_modules \
  --exclude-dir=plans --exclude-dir=handoffs .   # expect: only .claude/plans/**
```

## Definition of done

- Both YAML files parse.
- The grep above returns nothing outside the three preserved history directories.
- PR opened into `company-main`, babysat to green, admin-merged
  (`gh pr merge <N> --squash --admin --delete-branch`).
- The merge triggers a deploy as normal — dual-targeting keeps the trigger live. Confirm it
  goes green before starting Phase 2.
