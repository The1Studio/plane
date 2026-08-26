# Phase 2 — Delete `origin/master`, rename `company-main` → `master`

**Effort:** S (~0.5h) · **Depends on:** Phase 1 merged and its deploy green

The order inside this phase is not negotiable: the rename target name is occupied, and GitHub
refuses a rename onto an existing branch.

## Step 1 — Record the SHA being discarded

Per decision D2 the content is discarded with no archive tag. Record the SHA in the PR/commit
message anyway, so the ref reflog can be used within GitHub's retention window:

```bash
git rev-parse origin/master     # expect 88b609e6ce...
```

Its two unique commits are `88b609e6ce` (merge of PR #1) and `cb5d310eb9`
(`chore(claude): add Plane-specific dev skills and CLAUDE.md guide`), together 924 lines:
`.claude/skills/{backend-django,editor-ui,frontend-state,monorepo}/` and a tracked `CLAUDE.md`.

## Step 2 — Confirm the preconditions still hold

```bash
gh pr list --state open --json number          # must be []
gh repo view The1Studio/plane --json defaultBranchRef   # must still be company-main
```

If a PR has been opened since planning, stop — GitHub retargets open PRs on rename, and that
should be a conscious choice rather than a side effect.

## Step 3 — Delete `origin/master`

```bash
git push origin --delete master
```

Expected to succeed: ruleset `20970827` scopes its `deletion` rule to `~DEFAULT_BRANCH`, and
`master` is not the default. If it is blocked anyway, fall back to the admin API:

```bash
gh api -X DELETE repos/The1Studio/plane/git/refs/heads/master
```

## Step 4 — Rename on GitHub

The API is the right instrument — it moves the default-branch pointer, retargets any open PRs,
and preserves rulesets in one atomic operation. Doing it as a local `push` + `set-default` +
`delete` does not.

```bash
gh api -X POST repos/The1Studio/plane/branches/company-main/rename -f new_name=master
```

If the ruleset's `update` or `non_fast_forward` rules block it, temporarily set enforcement to
`disabled`, rename, then restore `active` — and verify the restore in Step 5 rather than
assuming it.

## Step 5 — Verify the rename took, and that protection followed

```bash
gh repo view The1Studio/plane --json defaultBranchRef        # expect master
gh api repos/The1Studio/plane/rulesets/20970827 \
  --jq '{enforcement, include: .conditions.ref_name.include}'
# expect: enforcement "active", include ["~DEFAULT_BRANCH"]
git ls-remote --heads origin | grep -E 'company-main|master'  # expect master only
```

The ruleset check is the one that actually matters. `~DEFAULT_BRANCH` is a symbolic target, so
protection _should_ follow the rename — but "should" is exactly the kind of claim this phase
exists to test. An unprotected production branch is a worse outcome than a failed rename.

## Definition of done

- Default branch is `master`.
- No `company-main` ref on origin.
- Ruleset `20970827` reports `enforcement: active` targeting `~DEFAULT_BRANCH`.
