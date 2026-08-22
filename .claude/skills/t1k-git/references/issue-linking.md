---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# t1k-git — Linking Commits / PRs / Branches to Issues (Detail)

Full detail backing SKILL.md § "Linking Commits / PRs / Branches to Issues". Associate work
with the issue it resolves so GitHub builds the cross-reference trail and auto-closes on merge.

## Keywords in commit messages and PR bodies

| Intent | Keywords | Effect |
|---|---|---|
| Close the issue on merge | `Closes #N` · `Fixes #N` · `Resolves #N` (also closed/fixed/resolved) | Auto-closes #N **when the commit/PR lands on the repo's DEFAULT branch** |
| Reference without closing | `Refs #N` · `Part of #N` · bare `#N` | Creates a timeline cross-reference; issue stays open |
| Cross-repo | `owner/repo#N` (e.g. `Fixes The1Studio/StickmanForge_IdleRPG#8`) | Same, targeting another repo |

- **Default-branch rule:** closing keywords auto-close ONLY when merged into the repo's *default* branch. A `Fixes #N` merged into a non-default branch (e.g. `develop` when default is `main`) will NOT close the issue until it reaches the default branch.
- **Prefer PR-level over commit-level:** put `Fixes #N` in the PR body (`gh pr create --body $'...\n\nFixes #N'`). One closing keyword in the PR closes the issue when the PR merges.
- **Multiple issues:** repeat the full keyword — `Fixes #3, Fixes #4`. A bare list `Fixes #3, #4` closes ONLY #3.

## Branch → issue

A branch name like `8-anim-groups` does NOT auto-link to issue #8. To create a branch GitHub actually links to the issue:
```bash
gh issue develop <N> --name <branch> --base <base-branch>   # creates + links a branch to issue #N
```
or use the issue's **Create a branch** link in the Development sidebar.

## PR dependencies & merge order

When a PR depends on another PR — same repo or cross-repo — state the dependency **and the required merge order in the PR body**, so a reviewer never lands them out of order. GitHub has no native "blocked-by" for PRs, so this is manual and mandatory whenever a dependency exists.

- **Declare it explicitly:** add a line the reviewer can't miss — `Depends on #N` (same repo) or `Depends on owner/repo#N` (cross-repo) — then spell out the order in words (`merge owner/repo#N first`).
- **Classify the coupling** so the reviewer knows how strict the order is:
  - **Hard (build-time):** the dependent PR won't compile / passes CI only after the base merges → base **MUST** merge first.
  - **Soft (functional/runtime):** both build independently, but a feature is broken until both land → merge **together or base-first**; say which and what breaks otherwise.
- **Cross-repo pairs:** name the paired PR in **both** PR bodies (each links the other) and pick ONE issue as the tracker. Typical case: a client/consumer PR + a contract/schema PR that must ship together — e.g. "merge `owner/contracts#44` first (or together); no build-time coupling, but the client 404s without it."
- **Stacked PRs (same repo):** base each branch on the previous one (not the default branch) and list the stack order (`1 → 2 → 3`) in every body; merge bottom-up.
- **Never auto-merge a PR with an unmet dependency**, even when green — surface the order and leave the merge to a human.

This complements the closing keywords above: `Fixes #N` says *what it closes*; the dependency note says *what must merge first*.
