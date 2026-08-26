# Phase 3 — Delete `preview` and the 8 merged heads; local cleanup

**Effort:** S (~0.5h) · **Depends on:** Phase 2 complete

## Step 1 — Delete `origin/preview`

`origin/preview` is 65 commits behind `upstream/preview` and its only two unique commits are a
feature and its own revert (`9961feccb0` then `dac6b2a101`), so it carries no content:

```bash
git push origin --delete preview
```

Nothing depends on it. The upstream workflows that trigger on `preview`
(`build-branch.yml`, `copyright-check.yml`, `pull-request-build-lint-{api,web-apps}.yml`) are
already dormant — they never fired on `company-main` either. Phase 1's grep should already
have caught any skill that checks it out; if one surfaces now, fix it before deleting.

## Step 2 — Delete the eight merged head branches

Each maps to a PR already merged into the production branch. Ancestry reports them "unmerged"
only because squash-merge produces a new SHA — verified instead against `gh pr list --state
merged`:

| Branch                                             | PR  |
| -------------------------------------------------- | --- |
| `feat/workload-unestimated-placeholder`            | #80 |
| `docs/workload-unestimated-propagation`            | #81 |
| `feat/workload-compact-unestimated-lanes`          | #82 |
| `fix/workload-placeholder-budgets-and-pack-window` | #83 |
| `docs/workload-packspan-comment`                   | #84 |
| `fix/workload-packwindow-rounding-slack`           | #85 |
| `fix/workload-pack-placeholders-into-lanes`        | #86 |
| `fix/workload-footer-overflow-double-count`        | #87 |

```bash
for b in feat/workload-unestimated-placeholder docs/workload-unestimated-propagation \
         feat/workload-compact-unestimated-lanes fix/workload-placeholder-budgets-and-pack-window \
         docs/workload-packspan-comment fix/workload-packwindow-rounding-slack \
         fix/workload-pack-placeholders-into-lanes fix/workload-footer-overflow-double-count; do
  git push origin --delete "$b"
done
```

## Step 3 — Local cleanup

The working clone has one worktree at the repo root on `company-main`, plus three other local
branches. `git branch -m` renames the checked-out branch in place, so no checkout dance is
needed:

```bash
git branch -m company-main master
git fetch origin --prune
git branch -u origin/master master
git remote set-head origin -a          # repoints origin/HEAD to master

git branch -D preview \
              docs/plan-compact-all-timelines \
              fix/workload-timeline-create-cell
```

The last three are all safe to force-delete: `preview` is being removed by decision, and the
other two already show `: gone` against their upstreams (their PRs were squash-merged, so `-d`
would refuse them — this is the documented `-D` case, not a shortcut).

## Step 4 — Verify

```bash
git branch -vv                         # expect: * master -> origin/master, alone
git branch -r                          # expect: origin/HEAD -> origin/master, origin/master
git status --short                     # expect: empty
```

## Definition of done

- `git branch -r` lists exactly `origin/HEAD -> origin/master` and `origin/master`.
- The local clone has one branch, `master`, tracking `origin/master`, working tree clean.
