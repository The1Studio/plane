# Phase 6 — Documentation: branch model and rebase policy

**Plan:** [`plan.md`](plan.md) · **Depends on:** [Phase 5](phase-5.md)
**Effort:** S (~0.5 day)

## Goal

Write the `staging` branch into the fork's governance documents, so the promotion path and — above
all — the **mandatory post-rebase reset** survive past this session. Nothing here is optional
polish: the reset step is the one thing standing between the chosen branch model and permanent
divergence.

## Files owned

- `docs/FORK.md`
- `.claude/rules/plane-fork-discipline.md`

Do not touch `CLAUDE.md` — it is gitignored local operator state, recreated from `docs/FORK.md`,
which is the SSOT. Update the SSOT and it follows.

## Why this phase is not optional

`docs/FORK.md` already assumes a staging stack exists. Its rebase recipe, step 7, reads:

```
# 7. Staging: migrate + smoke
#    docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm migrator
#    Run the Phase-5 smoke checklist against the staging stack.
```

That instruction has been unrunnable since it was written — there was no staging stack, and the
compose file names it cites (`docker-compose.prod.yml`) are not what the self-hosted deployment
uses. This phase makes step 7 real and correct at the same time as it documents the new branch.

## Changes

### 1. `docs/FORK.md` § "Branch model" — add the `staging` row

The table currently lists `master`, `sp1/clickup-migrate`, and `sp2/ai-ext`. Add:

| Branch    | Purpose                                                                                                                                                                                           | Rebases onto                       |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `staging` | Integration branch — features merge here first, then promote to `master`. Deployed to `staging-plane.the1studio.org`. **Disposable history**: hard-reset to `master` after every upstream rebase. | _never rebased_ — reset, see below |

Then amend the prose beneath the table. It currently says feature branches "are never merged
directly to `master` — instead, changes ride the rebase cycle." That is now only half true and must
be corrected rather than left to contradict the new row: features merge into `staging`, and
`staging` promotes to `master` by PR.

Also amend the line at `docs/FORK.md:1107` — _"A merge to `master` is a production deployment."_
Add its sibling: **a push to `staging` is a staging deployment**, and promotion to `master` is
therefore the release action.

### 2. `docs/FORK.md` § "Rebase-on-tags workflow" — fix step 7, add step 9

**Rewrite step 7** to reference the real staging stack:

```
# 7. Staging: deploy the rebase candidate and smoke it
#    gh workflow run deploy-staging.yml -f ref=<your-rebase-branch>
#    Then run the smoke checklist against https://staging-plane.the1studio.org
```

This is what the `workflow_dispatch` `ref` input from Phase 2 is _for_: validating a rebase
candidate on the real staging stack without force-pushing `staging` first.

**Add a new step 9, after the tag step**, and mark it mandatory:

```
# 9. MANDATORY — resync staging to the rebased master
#    The rebase rewrote master's history. staging was branched from the OLD history and is
#    now divergent by the entire rebased range. Reset it; do not attempt to merge.
git checkout staging
git reset --hard master
git merge feature/<each-branch-still-awaiting-promotion>   # repeat per open feature
git push --force-with-lease origin staging
```

Write the _why_ alongside it, not just the commands. The next person to run a rebase needs to
understand that staging's merge history is **deliberately disposable** — every feature's commits
reach `master` through its own promotion PR, so nothing is lost by discarding staging's merge
commits, and attempting to reconcile them instead produces a conflict fight that recurs every
month.

State the consequence of skipping it plainly: staging drifts permanently, every subsequent
promotion PR shows the entire upstream rebase as a diff, and the staging deployment stops
representing anything `master` will become.

Note the interaction with branch protection: if `staging` has protection enabled, force pushes
must be permitted for administrators or step 9 is blocked (Phase 4 step 7 flags the same tension
from the other side).

### 3. `docs/FORK.md` — deployment section

Wherever the self-hosted deployment is described, add the two-environment table (branch → workflow
→ run dir → compose project → ports → domain) and link to `deployments/selfhost/README.md`
(Phase 3) as the operational runbook. Keep `FORK.md` governance-level: the branch model, the
promotion path, and the rebase policy. Operational detail — how to deploy an arbitrary ref, how to
clone the database, what to check on failure — lives in the README, and duplicating it here
guarantees the two drift.

### 4. `.claude/rules/plane-fork-discipline.md`

This rule auto-loads into every session in this repo, so it is what actually prevents the reset
from being forgotten mid-rebase. Keep the additions short — it is a summary that points at
`docs/FORK.md`, not a second copy of it.

Add to the top matter, alongside the existing branch guidance:

- `staging` is the integration branch; it deploys to `staging-plane.the1studio.org` on every push.
- Features merge to `staging`, then promote to `master` by PR. `master` remains the only
  production branch.
- **After any `git rebase <upstream-tag>` on `master`, `staging` MUST be hard-reset to `master`
  and open features re-merged.** Its history is disposable by design. See `docs/FORK.md` §
  "Rebase-on-tags workflow" step 9.

Extend the existing **"After every rebase"** section — which currently names
`makemigrations --check`, `manage.py check`, and `pnpm check` — with the staging resync as a
fourth item, so the rule's own checklist is complete rather than deferring the one step most
likely to be skipped.

## Success criteria

1. `grep -c staging docs/FORK.md` ≥ 6, and the branch-model table contains a `staging` row.
2. `docs/FORK.md` step 7 no longer references `docker-compose.prod.yml` — verify with
   `grep -n 'docker-compose.prod.yml' docs/FORK.md`, which must return nothing (or only historical
   references outside the rebase recipe).
3. A step 9 exists in the rebase recipe containing `git reset --hard master` and
   `--force-with-lease`.
4. `.claude/rules/plane-fork-discipline.md` names `staging`, the promotion direction, and the
   post-rebase reset, and its "After every rebase" list has four items.
5. A reader who has never seen this plan can, from `docs/FORK.md` alone, answer: where does a
   feature branch merge, what deploys where, and what happens to `staging` after a rebase. Confirm
   by reading the section start to finish — not by grepping for the keywords you just added.

## Out of scope

- `CLAUDE.md` (gitignored local state, regenerated from `docs/FORK.md`).
- `deployments/selfhost/README.md` — Phase 3 owns it.
- Any change to the touch-point table or the isolation convention: this plan adds no Django app,
  no frontend package, and no core edit, so the seven touch-points are untouched.
