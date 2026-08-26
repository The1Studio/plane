# Rename `company-main` → `master`, delete stale `master` + `preview`

**Created:** 2026-08-26
**Repo:** The1Studio/plane (public, NOT a GitHub fork — `upstream` is a plain git remote)
**Branch model source of truth:** `docs/FORK.md`

---

## Goal

Retire the `company-main` branch name in favour of `master`, and remove three classes of
dead branch from `origin`:

1. `origin/master` — an early fork snapshot, deleted outright (content discarded, decided).
2. `origin/preview` — a stale upstream mirror, 65 commits behind `upstream/preview`.
3. Eight leftover head branches from squash-merged PRs #80–#87.

---

## Decisions (resolved, not open)

| #   | Decision                                   | Resolution                                                                                                                                                                                                   |
| --- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | Which branch did "review" mean             | `preview`. Delete it (local + origin).                                                                                                                                                                       |
| D2  | Fate of `origin/master`'s 924 unique lines | **Delete outright.** No archive tag. The four skills (`backend-django`, `editor-ui`, `frontend-state`, `monorepo`) and its tracked `CLAUDE.md` are discarded.                                                |
| D3  | Rename target                              | `master`, accepting the name collision with upstream's live release branch.                                                                                                                                  |
| D4  | Upstream-owned workflows keyed on `master` | **Delete `check-version.yml` outright**; neuter `codeql.yml` by dropping `master` from its branch lists. Record both as core-edit exceptions in `docs/FORK.md`. No fork-side version-bump policy is adopted. |
| D5  | Eight merged head branches                 | Delete all eight.                                                                                                                                                                                            |

---

## Load-bearing findings

These were verified, not assumed. They drive the phase order.

**`upstream/master` is alive and is upstream's release branch.** Last commit `5f7d92784c`
(2026-08-23) is `release: v1.4.2 #9632`, matching the latest release tag; it sits 5 commits
ahead of `upstream/preview`. `docs/FORK.md`'s rebase workflow adopts upstream **tags**, which
is exactly the line `upstream/master` carries. After this rename, two different branches in
every clone are called `master`. Nothing breaks mechanically — `upstream/master` stays
remote-qualified — but FORK.md's rule _"Never rebase onto `preview`/`master`"_ becomes
ambiguous and must be rewritten to name `upstream/preview` / `upstream/master` explicitly.
This is the single highest-value doc edit in the whole change.

**`origin/master` never tracked upstream.** `upstream/master` is not an ancestor of it
(112 upstream-only vs 9 origin-only commits). `docs/FORK.md` line 16 describes `preview` and
`master` as "Upstream tracking branches — untouched"; for `master` that has never been true.
The row is deleted, not corrected.

**Renaming silently rewires CI in three ways:**

| Workflow                       | Current trigger                             | Consequence of a bare rename                                                                                |
| ------------------------------ | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `deploy-company-main.yml`      | `push: branches: [company-main]`            | **Production deploys stop silently.**                                                                       |
| `company-main-ci.yml`          | `push`/`pull_request` on `company-main`     | The fork's only CI gate goes dormant.                                                                       |
| `check-version.yml` (upstream) | `pull_request: branches: [master]`          | **Newly fires and fails every PR** unless `package.json` version differs from `master`. Deleted in Phase 1. |
| `codeql.yml` (upstream)        | `push`/`pull_request` on `master`           | Newly starts running on every push and PR.                                                                  |
| `upstream-sync-check.yml`      | `git checkout company-main` in two heredocs | Emits a rebase recipe naming a branch that no longer exists.                                                |

**The repository ruleset follows the rename automatically.** Ruleset `20970827` targets
`~DEFAULT_BRANCH`, not a literal name, so protection moves with the default branch. Its rules
are `deletion`, `non_fast_forward`, `update`, `required_linear_history`, `pull_request` — note
there are **no required status checks**, so CI is not a merge blocker, but a PR _is_ required.

**Zero open PRs.** Nothing needs retargeting; the rename cannot orphan review work.

**Historical records are deliberately left alone.** `plans/**`, `.claude/plans/**` and
`.claude/handoffs/**` reference `company-main` roughly 40 times. Those files record what was
true when they were written; rewriting them would falsify the record. Only _live_ references
— docs, rules, skills, workflows, scripts — are swept.

---

## Phase order and why it is not negotiable

`origin/master` must be deleted **before** the rename, because the rename target name is
occupied and GitHub refuses a rename onto an existing branch.

The CI retarget must land **before** the rename, and must be **dual-targeted**
(`[company-main, master]`) rather than a straight swap. A straight swap leaves a window in
which the branch is still `company-main` while every workflow listens for `master` — deploy
and CI both dead. Dual-targeting means no workflow is ever pointed at a branch that does not
exist. Phase 4 drops the `company-main` half once the rename is done.

One deliberate consequence: the Phase 1 merge itself will **not** trigger a production deploy,
because `deploy-company-main.yml`'s `paths-ignore` covers `**/*.md` and `docs/**` but not
`.github/workflows/**` — the workflow file change would normally deploy. Dual-targeting keeps
the trigger live, so the deploy fires as usual. If a deploy on a docs/CI-only change is
unwanted, dispatch it manually instead and note it in the PR.

---

## Phases

| Phase | Name                                                         | Effort    | Depends on     |
| ----- | ------------------------------------------------------------ | --------- | -------------- |
| 1     | Dual-target CI, neuter upstream workflows, sweep live docs   | M (~3h)   | —              |
| 2     | Delete `origin/master`, rename `company-main` → `master`     | S (~0.5h) | Phase 1 merged |
| 3     | Delete `preview` + 8 merged heads; local branch cleanup      | S (~0.5h) | Phase 2        |
| 4     | Verify deploy pipeline, drop the `company-main` trigger half | S (~1h)   | Phase 3        |

**Total: ~5h. Critical path: 1 → 2 → 3 → 4** (strictly sequential; no parallel lanes).

Detail per phase lives in `phase-1.md` … `phase-4.md`.

---

## Risk Assessment

| Risk                                                             | Likelihood | Impact | Score  | Mitigation                                                                                                                                                                                    |
| ---------------------------------------------------------------- | ---------- | ------ | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Production deploys stop silently after rename                    | 4          | 5      | **20** | Dual-target `deploy-company-main.yml` in Phase 1 _before_ renaming; Phase 4 gate is an actual dispatched deploy run observed green, not an inspection of the YAML.                            |
| `check-version.yml` red-blocks every future PR                   | 4          | 4      | **16** | Delete the file in Phase 1, in the same PR as the rename prep. Verified in Phase 4 by opening a real PR into `master` and confirming the check is absent from its check list.                 |
| Future rebase confuses our `master` with `upstream/master`       | 4          | 4      | **16** | Rewrite FORK.md's rebase rule to name `upstream/master` / `upstream/preview` explicitly, and add a named warning block. Sweep `plane-rebase` skill (10 refs) the same way.                    |
| Ruleset does not survive the rename                              | 2          | 4      | 8      | It targets `~DEFAULT_BRANCH`, so it should follow. Phase 2 re-reads the ruleset after renaming and asserts `enforcement: active`. Fallback: set enforcement to `disabled`, rename, re-enable. |
| `git push origin --delete master` blocked by the `deletion` rule | 2          | 3      | 6      | The rule scopes to `~DEFAULT_BRANCH`, and `master` is not the default. If it blocks anyway, delete via `gh api -X DELETE .../git/refs/heads/master` as an admin.                              |
| Deleting `preview` breaks a skill that checks it out             | 2          | 3      | 6      | Phase 1 greps `.claude/skills/` for `origin/preview` before deletion and fixes any consumer.                                                                                                  |
| The discarded 924 lines are wanted later                         | 2          | 2      | 4      | Accepted per D2. Recoverable from GitHub's ref reflog only, and only for a limited window. SHA recorded here: `88b609e6ce`.                                                                   |

No risk scores ≥ 15 are left unmitigated.

---

## Success criteria

- `gh repo view The1Studio/plane --json defaultBranchRef` reports `master`.
- `git branch -r` shows no `origin/company-main`, no `origin/preview`, and none of the eight
  merged head branches.
- A dispatched run of the deploy workflow completes green against `master`.
- A PR opened into `master` shows the fork CI gate running and shows **no**
  "Version Change Before Release" check.
- `grep -rn "company-main" --exclude-dir=.git` returns hits **only** under `plans/`,
  `.claude/plans/`, and `.claude/handoffs/` — the deliberately-preserved historical record.
- Ruleset `20970827` still reports `enforcement: active` and still targets `~DEFAULT_BRANCH`.

---

## Out of scope

- Relinking `The1Studio/plane` as a GitHub fork of `makeplane/plane`. Only GitHub Support can
  set a fork parent retroactively; it would also permanently prevent the repo going private
  and would default `gh pr create` to the upstream repo. Recommended against, separately.
- Renaming the workflow _files_ (`deploy-company-main.yml`, `company-main-ci.yml`). Their names
  become misleading, but they are named in FORK.md's touch-point table and renaming them adds
  doc churn for no functional gain. Tracked as a follow-up, not done here.
- The dormant upstream workflows that key on `preview` (`build-branch.yml`,
  `copyright-check.yml`, `pull-request-build-lint-{api,web-apps}.yml`). They already never fire
  on our branches; deleting `preview` changes nothing for them.
- Sibling-repo propagation. This change adds no endpoint, field, or behaviour, so the standing
  propagation rule in `CLAUDE.md` does not apply.

---

## Tracking

Plane project **PLANE** (workspace `infrastructure`), all items in **Todo**, assigned to manhnd.

| Item                                                                                | Phase   | Est          |
| ----------------------------------------------------------------------------------- | ------- | ------------ |
| [PLANE-182](https://plane.the1studio.org/infrastructure/browse/PLANE-182/) — parent | —       | derived (5h) |
| [PLANE-183](https://plane.the1studio.org/infrastructure/browse/PLANE-183/)          | Phase 1 | 3h           |
| [PLANE-184](https://plane.the1studio.org/infrastructure/browse/PLANE-184/)          | Phase 2 | 0.5h         |
| [PLANE-185](https://plane.the1studio.org/infrastructure/browse/PLANE-185/)          | Phase 3 | 0.5h         |
| [PLANE-186](https://plane.the1studio.org/infrastructure/browse/PLANE-186/)          | Phase 4 | 1h           |
