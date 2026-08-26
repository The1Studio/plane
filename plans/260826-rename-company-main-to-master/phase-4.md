# Phase 4 — Prove the pipeline, then drop the `company-main` trigger half

**Effort:** S (~1h) · **Depends on:** Phase 3 complete

Phase 1 deliberately left every fork workflow listening on **both** `company-main` and
`master`. Those branches no longer exist under the old name, so the `company-main` half is now
dead weight that misleads the next reader. This phase removes it — but only _after_ proving
the `master` half actually works.

Order matters: verify first, then edit. Editing first and verifying afterwards means a failure
has two candidate causes.

## Step 1 — Prove the deploy pipeline against `master`

This is the gate that the plan's highest-scoring risk (score 20) depends on. Reading the YAML
is not evidence — a dispatched run that completes green is:

```bash
gh workflow run "Deploy company-main (self-hosted)" --ref master
gh run list --workflow deploy-company-main.yml --limit 1
gh run watch <run-id>
```

The run must actually execute on the self-hosted `sv-0` runner and reach a green conclusion.
A run that is queued-and-cancelled, or that skips its deploy job, does not count.

If it fails, stop and diagnose before touching triggers — a red deploy here means production
is not deployable from `master`, which is a strictly worse state than before this plan started.

## Step 2 — Confirm no upstream workflow woke up on `master`

Phase 1 deleted `check-version.yml` and dropped `master` from `codeql.yml`'s branch lists. The
proof is a real PR's check list, not an inspection of the YAML — a PR into `master` is the only
thing that can make either workflow fire, so nothing before this point could have detected a
failure. Open the Phase 4 PR (Step 3) and read:

```bash
gh pr checks <N>
```

The fork CI gate must appear. **"Version Change Before Release" must not** — if it does, the
deletion did not land and every future PR is red-blocked on a mandatory version bump. CodeQL
must not appear either.

## Step 3 — Drop the `company-main` half

| File                                        | Edit                                                                                                                                                                                                |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.github/workflows/company-main-ci.yml`     | `push.branches` and `pull_request.branches`: `[company-main, master]` → `[master]`; `name: company-main CI` → `name: master CI`                                                                     |
| `.github/workflows/deploy-company-main.yml` | `push.branches`: `[company-main, master]` → `[master]`; `name: Deploy company-main (self-hosted)` → `name: Deploy master (self-hosted)`; `concurrency.group: deploy-company-main` → `deploy-master` |

Phase 1 deliberately left the two `name:` fields and the concurrency group alone: Step 1 above
dispatches the deploy **by its display name**, so renaming it earlier would have invalidated
that command, and changing a concurrency group mid-transition could let two deploys overlap.
Both are safe to change now — the group name is arbitrary, and no ruleset requires a status
check by name (ruleset `20970827` has no `required_status_checks` rule).

Open as a PR into `master`, use it for Step 2's check-list reading, babysit to green, then
`gh pr merge <N> --squash --admin --delete-branch`.

Note that merging this PR _will_ trigger a real production deploy — the workflow-file path is
not covered by `paths-ignore`. That is fine and is in fact a second confirmation of Step 1.

## Step 4 — Final sweep

```bash
grep -rn "company-main" --exclude-dir=.git --exclude-dir=node_modules .
```

Every remaining hit must be under `plans/`, `.claude/plans/`, or `.claude/handoffs/` — the
preserved historical record. A hit anywhere else is a miss from Phase 1.

```bash
gh repo view The1Studio/plane --json defaultBranchRef
git branch -r
gh api repos/The1Studio/plane/rulesets/20970827 --jq '.enforcement'
```

## Follow-ups, deliberately not done here

- **Rename the workflow files** (`deploy-company-main.yml` → `deploy-master.yml`,
  `company-main-ci.yml` → `master-ci.yml`). Their names are now misleading, but they are cited
  by filename in `docs/FORK.md`'s touch-point table (lines ~1055–1056) and in
  `deployments/selfhost/*.sh` comments, so a rename is pure doc churn for zero functional gain.
  Worth doing as its own small PR when someone is next in those files.
- **Relinking to `makeplane/plane` as a GitHub fork.** Only GitHub Support can set a fork parent
  retroactively; it would also permanently block the repo from going private and would default
  `gh pr create` to the upstream repo. Recommended against — the `upstream` git remote already
  supplies everything the rebase-on-tags workflow needs.

## Definition of done

- A dispatched deploy run against `master` completed green on the `sv-0` runner.
- A PR into `master` showed the fork CI gate and showed neither "Version Change Before
  Release" nor CodeQL.
- No workflow references `company-main` in a trigger, display name, or concurrency group.
- The repo-wide grep returns hits only under the three preserved history directories.
