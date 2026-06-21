---
name: plane-rebase
description: Rebase company-main onto an upstream Plane CE tag per docs/FORK.md — classify conflicts, auto-resolve touch-points, abort on leaks. Use for "rebase onto upstream tag", "run the monthly rebase", "sync fork to upstream".
keywords: [rebase, upstream, fork, company-main, touch-point, rerere, sync]
metadata:
  author: the1studio
  version: "1.0.0"
---

> **HARD-GATE contract:** `rules/workflow-gates.md` (global). This skill uses two
> `<HARD-GATE>` blocks — A (leak-abort, no override) and B (pre-push, requires explicit
> user confirmation). Both MUST fire; no flag bypasses Gate A.

---

## When to Use

Invoke this skill when you need to adopt a new upstream Plane CE release tag onto
`company-main`. It drives the full cycle defined in `docs/FORK.md` §Rebase-on-tags —
classifying every conflict, auto-resolving documented touch-points (1–6) via per-touch-point
recipes, and performing two mandatory stops: one on any leak, and one before pushing the
result.

Do NOT run an actual rebase, `pnpm install`, or `makemigrations` unless `docs/FORK.md` is
fully read and the working tree is clean. This skill does not execute on your behalf without
user confirmation at Gate B.

---

## Activation

Trigger phrases (any of these activates this skill):

- "rebase onto upstream tag"
- "adopt upstream Plane CE tag"
- "run the monthly rebase"
- "sync fork to upstream"
- "rebase company-main onto vX.Y.Z"

---

## The Cycle

This cycle mirrors `docs/FORK.md` §Rebase-on-tags workflow exactly. `docs/FORK.md` is the
SSOT — on any discrepancy, FORK.md wins.

### Step 1 — Fetch upstream tags

```bash
git fetch upstream --tags
```

Confirm `upstream` remote points to `https://github.com/makeplane/plane`. If the remote is
missing: `git remote add upstream https://github.com/makeplane/plane`.

### Step 2 — Identify the target tag

```bash
git tag -l 'v*' | sort -V | tail -10
```

Pick the tag to adopt. Cadence guideline from `docs/FORK.md`: do not skip more than two
consecutive upstream tags — the conflict surface grows quickly. If the candidate tag is more
than 2 tags ahead of the current `company-main` base, warn the user before proceeding.

### Step 3 — Verify clean tree and switch to company-main

```bash
git status --short   # must be empty
git checkout company-main
```

If the working tree is not clean, STOP and ask the user to stash or commit pending changes
before running the rebase.

### Step 4 — Start the rebase

```bash
git rebase <tag>     # e.g. git rebase v1.4.0
```

If the rebase completes with zero conflicts, jump to Step 6.

### Step 5 — Conflict triage (per-conflict loop)

For each unresolved file (`git diff --name-only --diff-filter=U`), run the classifier:

```bash
node .claude/scripts/plane-classify-path.cjs <conflicted-file>
```

The classifier returns JSON `{path, category, touchPointId, reason}`.

#### Decision tree on `category`:

| `category` value | Action                                                                                                                                                                                                                                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `touch-point`    | Auto-resolve: check if `git rerere` already replayed (see §git rerere). If replayed → `git add <file> && git rebase --continue`. If NOT replayed → apply the per-touch-point recipe from `references/rebase-recipe.md` → `git add <file> && git rebase --continue`.                                          |
| `custom-app`     | These files are entirely fork-owned (under `apps/api/plane/<fork-app>/`). Upstream should not have conflicting edits here; if they do, the upstream edit is wrong in scope. Resolve by keeping the fork version, then `git add <file> && git rebase --continue`. Investigate why upstream touched this path. |
| `custom-package` | Same as `custom-app` — fork-owned. Keep fork version, continue.                                                                                                                                                                                                                                              |
| `core`           | **HARD-GATE A fires immediately. See below. Never --continue.**                                                                                                                                                                                                                                              |

Additionally: if a touch-point file shows as DELETED or RENAMED upstream (`git diff --name-only
--diff-filter=D` or `--diff-filter=R`), that is a relocation event — HARD-GATE A also fires
(step 3 of `docs/FORK.md` §Conflict recovery).

<HARD-GATE id="A" label="Leak-abort" override="none">

**Gate A — Leak-abort (NO override exists)**

**Fires when:** any conflicted file is classified `core` by `plane-classify-path.cjs`, OR
when a touch-point file has been deleted or renamed upstream.

**Mandatory action:**

```bash
git rebase --abort   # restores company-main to its pre-rebase state
```

After abort, use `AskUserQuestion` to surface:

1. The leaked file path.
2. Its classifier output (`category: "core"`, `reason`).
3. The required relocation: move the out-of-bounds edit into a new Django app
   (`apps/api/plane/<new-app>/`) or a new frontend package (`packages/<name>-ext/`),
   wired through the documented touch-points (1–6).
4. For a renamed/deleted touch-point: the upstream's new path and a request for the user
   to confirm the re-homing plan before the rebase is retried.

**No flag bypasses this gate.** `--force`, `--fast`, `--skip`, or any override phrase does
NOT apply. A `core` conflict means the isolation convention was violated before this rebase
started; auto-resolving it buries the problem and compounds it on every future rebase.

Per `docs/FORK.md` §Conflict recovery step 4: "Do not resolve-and-continue — the leak will
compound with every future rebase."

</HARD-GATE>

### Step 6 — Rebuild and type-check

After all conflicts are resolved and `git rebase --continue` finishes:

```bash
pnpm install
pnpm check
```

Both must exit 0. If `pnpm check` fails (TypeScript errors, lint), fix them before
proceeding — they indicate the upstream changes are incompatible with fork code.

### Step 7 — Django system check and migration gate

```bash
cd apps/api
python manage.py makemigrations --check --dry-run
python manage.py check
```

`makemigrations --check` must report no missing migrations (the CI gate in
`company-main-ci.yml` enforces this on every push). Fix any missing migrations in the
affected fork app before proceeding.

### Step 8 — Pre-push gate (HARD-GATE B)

<HARD-GATE id="B" label="Pre-push confirmation" override="explicit user confirmation ('push' or 'yes, push')">

**Gate B — Pre-push (override: explicit user confirmation)**

Before tagging and pushing, STOP and present a summary to the user via `AskUserQuestion`:

- **Upstream tag adopted:** `<tag>` (e.g. `v1.4.0`)
- **Planned company tag:** `company-v<tag>-<N>` (increment N if a prior tag exists for the
  same upstream tag, e.g. `company-v1.4.0-2` after a hotfix)
- **Conflicts encountered:** list each file and how it was resolved (rerere replay, recipe
  applied, or custom-app/package kept)
- **pnpm check:** pass / fail + error count
- **makemigrations --check:** pass / fail
- **django check:** pass / fail

Push **only** on explicit user confirmation ("push", "yes push", "go ahead", or equivalent
affirmative). If the user asks for changes (re-run check, fix a migration), carry them out
before re-presenting this gate.

On confirmation:

```bash
git tag company-v<tag>-<N>
git push origin company-main --tags
```

</HARD-GATE>

---

## git rerere

`git rerere` (Reuse Recorded Resolution) is **already enabled** on this repo:

```
rerere.enabled = true
rerere.autoupdate = true
```

How it interacts with Step 5:

- When the rebase hits a conflict in a touch-point file that was previously resolved (in an
  earlier monthly rebase), `rerere` automatically replays the recorded resolution and stages
  the file.
- `rerere.autoupdate = true` means the file is auto-staged — you may see it move from
  "unresolved" to "staged" without manual `git add`.
- After rerere replays: verify the result looks sane (`git diff --staged <file>`), then
  `git rebase --continue`.
- If rerere replays incorrectly (upstream changed the surrounding context significantly):
  unstage, manually apply the correct recipe from `references/rebase-recipe.md`, re-stage,
  then continue.

Keep `.git/rr-cache/` intact across sessions. Do not prune it. Each correct resolution
recorded there removes a future manual step.

First-time resolution of a touch-point conflict: apply the recipe from
`references/rebase-recipe.md`, stage, continue — rerere records it automatically for next
time.

---

## References

- `docs/FORK.md` — SSOT for all fork governance (ALWAYS takes precedence over this skill)
- `.claude/skills/_shared/references/fork-convention.md` — machine-readable convention mirror
- `.claude/scripts/plane-classify-path.cjs` — deterministic path classifier
- `.claude/skills/plane-rebase/references/rebase-recipe.md` — per-touch-point resolution recipes
- `.claude/skills/plane-rebase/fixtures/seeded-leak-conflict.md` — dry-run scenario for Gate A
- `rules/workflow-gates.md` — universal HARD-GATE contract
