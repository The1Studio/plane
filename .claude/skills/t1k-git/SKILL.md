---
name: t1k:git
description: "Git operations with conventional commits. Stage, commit, push, PR, merge. Security scans for secrets. Auto-splits commits by scope."
keywords: [git, commit, push, branch, pull-request, stage, merge, issue-link, fixes, closes, lfs, large-files, binary-assets]
argument-hint: "cm|cp|pr|merge [args]"
effort: low
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Git — Git Operations

Unified git command. Routes to registered `t1k-git-manager` agent via routing protocol.

## Default (No Arguments)

Use `AskUserQuestion` to present available operations:

| Operation | Description |
|-----------|-------------|
| `cm` | Stage files and create commits |
| `cp` | Stage files, create commits, and push |
| `pr` | Create Pull Request |
| `merge` | Merge branches |

## Arguments
- `cm`: Stage files and create commits
- `cp`: Stage files, create commits, and push
- `pr [to-branch] [from-branch]`: Create Pull Request
- `merge [to-branch] [from-branch]`: Merge branches

## Core Workflow

### Step 1: Stage + Analyze
```bash
git add -A && git diff --cached --stat && git diff --cached --name-only
```

### Step 2: Security Check
```bash
git diff --cached | grep -iE "(api[_-]?key|token|password|secret|credential)"
```
**If secrets found:** STOP, warn user, suggest `.gitignore`.

### Step 2.5: Local Quality Gate — Lint + Typecheck

Before commit, run the kit's quality scripts if present. This catches CI-side failures (biome, eslint, ruff, tsc) that would otherwise bounce the PR.

```bash
# Auto-discover scripts
jq -r '.scripts | to_entries[] | select(.key | test("^(lint|typecheck|check)$")) | .key' package.json 2>/dev/null
```

Then run each discovered script (short-circuit on first failure):

| Script | Purpose | If fails |
|---|---|---|
| `typecheck` / `check` | Type-check source | STOP — fix types before commit |
| `lint` | Style/format check (biome/eslint/ruff) | STOP — run `bun run lint --write` or equivalent auto-fix, then re-check |

**Skip rules:**
- No `package.json`: skip (not a Node/Bun project). Check for `Cargo.toml`, `pyproject.toml`, etc.; run their equivalents (`cargo check`, `ruff check`).
- Script doesn't exist: skip that script silently.
- User explicitly passed `--skip-lint`: skip with a warning in output.
- Staged diff is 100% docs-only (all `*.md` / `docs/**`): skip — content rules only.

**Rationale:** Running lint before commit costs a few seconds; skipping it costs a full CI cycle + a fix-up commit that pollutes the PR history. (Three CI rounds once lost to biome format violations `bun run lint` would have caught locally — [references/incident-trail.md](references/incident-trail.md).)

### Step 2.7: Large-File / LFS Check

Staged binaries must go through Git LFS **before** they are committed — LFS cannot be retrofitted onto an already-committed blob without a history rewrite.

```bash
# Staged files over 5MB (the "should this be LFS?" candidates)
git diff --cached --name-only -z | xargs -0 -r du -m 2>/dev/null | awk '$1 >= 5 {print $1"MB\t"$2}'
# In a repo that already uses LFS: is each staged binary ACTUALLY routed to LFS?
git check-attr filter -- <file>        # "filter: lfs" = tracked; "unspecified" = will commit as a raw blob
```

| Finding | Action |
|---|---|
| Staged file ≥ 100MB | **STOP** — GitHub hard-rejects the push. Track via LFS (or unstage) before committing. |
| Staged binary ≥ 5MB (art, audio, video, models, archives, ML weights) in a repo **without** LFS | Suggest enabling: `git lfs install && git lfs track "*.<ext>"`, stage `.gitattributes`, THEN stage the binary. |
| Repo has `.gitattributes` LFS patterns but `git check-attr filter` says `unspecified` for a staged binary | **STOP** — the pattern misses this path; fix the pattern first. A pattern miss commits the raw blob silently and is only noticed when the repo balloons. |

Full rules + gotchas: [Large Binaries — Git LFS](#large-binaries--git-lfs) below.

### Step 3: Split Decision
Split commits if: different types mixed, multiple scopes, FILES > 10 unrelated.
Single commit if: same type/scope, FILES <= 3, LINES <= 50.

### Step 4: Commit
```bash
git commit -m "type(scope): description"
```

### Step 5: Plane Work-Item Update (after push)

Full contract — do not restate or reimplement it here:
[`skills/t1k-plane/references/workflow-enforcement.md`](../t1k-plane/references/workflow-enforcement.md)
§ Stage 4. Governing rule: `modules/t1k-extended/rules/plane-workitem-workflow.md`.

Comment the commit SHA(s) and branch on every work item bound to this session, then
apply `doneTrigger: pr-merge-else-push`:

| Situation | Action |
|---|---|
| Pushed, no PR opened for the branch | Advance to **Done** (`completed` state group) |
| PR opened (`/t1k:git pr`) | Comment the PR URL — **do NOT** set Done; Done fires at merge |
| Pushed to a branch with an open, unmerged PR | Comment the SHA only |
| PR merged (`/t1k:git merge`) | Comment the merge SHA, then advance to **Done** |

`t1k-plane-binding.cjs session stage --stage done` guards the double transition when
push and merge both land in one session. Degrades to a single warning when the `plane`
MCP server is absent, `T1K_PLANE_MODE` is `advisory`/`off`, or `--no-plane` was passed.

## Output Format
```
staged: N files (+X/-Y lines)
security: passed
commit: HASH type(scope): description
pushed: yes/no
plane: PROJ-N → Done | commented | skipped (reason)
```

## Linking Commits / PRs / Branches to Issues

Associate work with the issue it resolves so GitHub builds the cross-reference trail and
auto-closes on merge. `Closes`/`Fixes`/`Resolves #N` — preferably in the **PR body**, not the
commit — auto-closes #N when the PR merges into the repo's **default branch only**; `Refs #N`
cross-references without closing. A branch name like `8-anim-groups` does NOT auto-link — use
`gh issue develop <N> --name <branch>` to create one that does. When a PR depends on another,
state it explicitly in the PR body (`Depends on #N`, hard-vs-soft coupling, merge order) —
GitHub has no native "blocked-by" for PRs, and an unmet dependency must never be auto-merged
even when green. Full keyword table, cross-repo rules, and PR-dependency detail:
[references/issue-linking.md](references/issue-linking.md).

### ⚠ Wiki commits do NOT link to issues

A repo's wiki is a **separate git repo** (`<repo>.wiki.git`) that lives OUTSIDE the issue/PR cross-reference graph. `Fixes #N` / `Refs #N` in a **wiki** commit message is **inert** — GitHub emits no timeline event and never auto-closes. To associate a wiki change with an issue:

1. Comment on the issue with the wiki page revision URL: `https://github.com/<owner>/<repo>/wiki/<Page>/<commit-sha>` (private-repo links require auth to open).
2. OR reference `#N` from a **main-repo** commit/PR (the only place keywords are honored) when the related code lands.

Incident: [references/incident-trail.md](references/incident-trail.md) § "Wiki commit cross-reference miss".

## Force-Push Safeguard

| Scenario | Action |
|----------|--------|
| `git push --force` on `main` or `master` | **BLOCKED** — warn user, refuse to execute |
| `git push --force` on any other branch | **WARNING** — ask for confirmation, suggest `--force-with-lease` |
| `git push --force-with-lease` anywhere | **ALLOWED** — safer alternative, proceed normally |

**Rule:** Never execute bare `--force` on protected branches (main, master, release/*). Always suggest `--force-with-lease` as the correct alternative — it fails if the remote was updated by someone else, preventing accidental overwrites.

Note: `secret-guard.cjs` hook already blocks credential exposure in commits. This rule extends to push safety.

## Large Binaries — Git LFS

Game-studio repos (Unity, Cocos, art, audio) hit GitHub's limits constantly: **>100MB per file is hard-rejected**, >50MB warns, and every large blob committed raw bloats the clone for everyone forever. LFS is the answer — but only when wired BEFORE the commit.

### Enable + track

```bash
git lfs install                          # once per machine (writes the global filter config)
git lfs track "*.png" "*.fbx" "*.wav"    # writes patterns into .gitattributes
git add .gitattributes                   # attributes MUST land with or before the binaries
git add Assets/hero.fbx && git commit -m "feat(art): hero model"
git lfs ls-files                         # verify the blob went to LFS, not the object store
```

### Rules

`.gitattributes` must land before/with the binary (the filter applies at `git add` time, not
retroactively); retrofitting an already-tracked file needs a history-rewriting `git lfs migrate`
(force-push implications); track binary media only, never small text/config; every clone/CI
runner needs `git lfs install` or builds fail on pointer-file stubs. Full rules + rationale:
[references/lfs-rules.md](references/lfs-rules.md).

## Commit TYPE in Skill/Doc Kits — Shipped `.claude/` Content Is `fix`/`feat`, NOT `docs`

In a TheOneKit kit the shipped product **is** the `.claude/` payload — skill `SKILL.md` bodies + their `references/`, agents, rules, registry fragments. Editing any of these changes **what consumers receive**, so it MUST use a **releasable** type:

| You edited… | Use |
|---|---|
| Skill body / `references/`, fixed a gotcha, corrected a pattern | `fix(<module>): …` |
| New skill, reference doc, agent, or capability | `feat(<module>): …` |
| Breaking change to a shipped skill/agent contract | `feat(<module>)!:` / `BREAKING CHANGE:` |
| `README.md`, `CONTRIBUTING.md`, `docs/**`, `plans/**`, code comments | `docs: …` (these never ship) |

**NEVER `docs(...)` for files under `.claude/`.** `docs`/`chore`/`style`/`test`/`ci` are no-bump — `parse-commits.cjs` skips them entirely, so the edit never ships and the kit silently stops releasing (`[release] No releasable commits since last tag — exiting`). The conventional-commits instinct "it's a `.md` edit → `docs:`" is **wrong here**: a skill `.md` is *product source*, not repo documentation. (The lint "diff is 100% docs-only → skip" rule earlier is about *lint-skipping*, NOT commit type.)

**Test before choosing `docs`:** does the edited file land in a consumer's `.claude/` on `t1k modules update`? Yes (path contains `/.claude/`, or it's a `SKILL.md` / agent `.md` / rule `.md`) → `fix`/`feat`. No (README/`docs/`/`plans/`) → `docs`.

Incident: [references/incident-trail.md](references/incident-trail.md) § "Skill edits committed as `docs(...)` never released".

## Commit Scopes in Modular Kits — Must Map to Real Modules

TheOneKit's release pipeline (`parse-commits.cjs` in `theonekit-release-action`) triggers a per-module version bump **only** when the commit scope matches one of:

- An exact module name (e.g. `feat(t1k-base):`, `fix(dots-core):`)
- A comma-separated list of module names (e.g. `feat(dots-core,dots-combat):`)
- The kit repo name (e.g. `feat(theonekit-unity):`) — bumps all modules
- One of the kit-wide meta-scopes: `modules`, `all`, `meta`, `kit` — bumps all modules
- Unscoped `feat`/`fix`/`refactor`/`perf` — bumps all modules
- Unscoped commit with `!` or `BREAKING CHANGE` — bumps all modules (major)

**Anything else is silently dropped.** `chore`, `docs`, `style`, `test`, `ci` are always no-bump. **Skill names are NOT module names.** `fix(t1k-handoff):`, `feat(t1k-doctor):`, `fix(t1k-modules):` all produce zero affected modules → the release workflow logs `[release] No releasable commits since last tag — exiting` and publishes nothing.

**Before committing a skill-level fix to a modular kit:** check which module owns the skill (`cat .claude/modules/*/module.json | jq '{name, skills}'`) and either:
- Use the owning module name as scope: `fix(t1k-base): ...` when editing `t1k-handoff` (since `t1k-handoff` is in `t1k-base`)
- OR use a meta-scope when the fix is kit-wide: `feat(modules): ...`

Incident: [references/incident-trail.md](references/incident-trail.md) § "`feat(modules):` unrecognized — stuck release".

## Contribution Scoring

After `pr` succeeds (not `cm`/`cp` — no artifact), invoke `t1k:contribution-score` with `type=sync-back-pr` + PR URL/title/body and target kit/repo. Fire-and-forget; SSOT gates non-T1K repos. See `.claude/skills/t1k-contribution-score/SKILL.md`.

## Scope

Git operations only. Never sync files containing credentials, API keys, or secrets.
