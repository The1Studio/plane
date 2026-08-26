---
name: plane-isolation-audit
description: Audit fork-isolation — scan tree/diff/PR for edits that leak into core, mirroring master CI gates. Use for "audit fork isolation", "did I leak into core", "will this pass master CI".
keywords: [fork, isolation, audit, leak, touch-point, master, ci-parity]
metadata:
  author: the1studio
  version: "1.0.0"
---

# plane-isolation-audit

Read-only audit skill. Scans a working tree, commit range, or PR diff for fork-convention
violations before they reach CI. No hard gates — runs to completion and reports a verdict.

SSOT: `docs/FORK.md`. Convention data mirror: `.claude/skills/_shared/references/fork-convention.md`.
Path verdicts are fully delegated to `.claude/scripts/plane-classify-path.cjs` — no parallel
classification logic lives here.

---

## When to Use

- Before opening a PR to `master`
- After resolving rebase conflicts, to confirm no leak crept in
- Before running the monthly upstream rebase (`git rebase <tag>`)
- Whenever you suspect a core edit slipped through

---

## Activation

Trigger phrases (any of these should activate this skill):

- "audit fork isolation"
- "check isolation"
- "did I leak into core"
- "will this pass master CI"
- "isolation audit"
- "pre-rebase isolation check"

---

## Decision Tree

```
Input scope?
 ├─ working tree   → git diff --name-only HEAD
 ├─ a commit range → git diff --name-only <base>..<head>
 └─ a PR number    → gh pr diff <N> --name-only

For each changed file → classify via plane-classify-path.cjs:
  core           → VIOLATION (report file + reason + relocation hint: "move to a new app/package")
  touch-point    → OK, but verify edit is APPEND-ONLY
                   (warn if an existing touch-point line was deleted or modified — diff must show
                    only "+" lines in the fork-specific block, no "-" lines)
  custom-app/pkg → OK
  custom-infra   → OK (fork-created infrastructure: deploy scripts, the fork's own CI workflows,
                   plans/, docs/FORK.md — see fork-convention.md "forkPaths")

Then content scans (apply to the full diff text, not just filenames):
  1. A new field added to a core-model class (Issue / Page / Module / State / Intake / Asset)?
     → VIOLATION — new columns on core models are forbidden; add a new table in a fork app.
  2. A new file created under apps/web/app/routes/ that is NOT extended.ts?
     → VIOLATION — only routes/extended.ts may carry fork route edits.

Output: a violation table (file | category | rule | fix) + overall PASS/FAIL verdict.
```

**Scope determination** — ask the user if not obvious:

| User says                          | Scope                                               |
| ---------------------------------- | --------------------------------------------------- |
| "current changes", "what I have"   | working tree (`git diff --name-only HEAD`)          |
| "this branch", "my branch vs main" | commit range (`git diff --name-only master...HEAD`) |
| "PR #N", "pull request N"          | PR diff (`gh pr diff N --name-only`)                |

---

## CI Parity

This skill mirrors the three checks in `.github/workflows/master-ci.yml`:

| CI command                                          | What it catches                                                               | Skill equivalent                                                                                         |
| --------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `python manage.py check`                            | Django system errors — import failures, URL resolver errors, bad model config | Flag any core-file edit that would break Django loading (core model columns, leaked URL config)          |
| `python manage.py makemigrations --check --dry-run` | Pending migrations — model change without a migration file                    | Flag new fields on core models (the change that causes this check to fail)                               |
| `pnpm check`                                        | TypeScript type errors after rebase                                           | Flag edits to `@plane/*` packages or `apps/web/app/routes/core.ts` (the edits that break the type-check) |

The skill catches the **cause** (the bad edit) before CI catches the **effect** (the failing check).
It does not re-run Django or the TypeScript compiler locally — it is a diff-level audit, not a
full build.

---

## Output

Report format (emit as a Markdown table + verdict line):

```
### Fork Isolation Audit — <scope>

| File | Category | Rule violated | Fix |
|------|----------|--------------|-----|
| apps/api/plane/db/models/issue.py | core | No edits to core files | Move new field to plane/workload/models.py with FK to Issue |
| apps/api/plane/app/views/issue/base.py | core | No edits to core files | Move view logic to plane/ai_ext/views.py |

**Verdict: FAIL** — 2 violation(s). Relocate before opening a PR.
```

On a clean diff:

```
### Fork Isolation Audit — working tree

No violations found. All changed files are touch-points or fork-owned.

**Verdict: PASS**
```

### Worked Example (fixture paths)

Running the classifier over the fixture files included in this skill:

```bash
node .claude/scripts/plane-classify-path.cjs \
  "apps/api/plane/db/models/issue.py" \
  "apps/api/plane/app/views/issue/base.py" \
  "apps/api/plane/settings/common.py" \
  "apps/api/plane/ai_ext/models.py"
```

Expected output:

```json
[
  {
    "path": "apps/api/plane/db/models/issue.py",
    "category": "core",
    "touchPointId": null,
    "reason": "core file (not a touch-point / fork app / fork package) — fork edits forbidden, relocate"
  },
  {
    "path": "apps/api/plane/app/views/issue/base.py",
    "category": "core",
    "touchPointId": null,
    "reason": "core file (not a touch-point / fork app / fork package) — fork edits forbidden, relocate"
  },
  {
    "path": "apps/api/plane/settings/common.py",
    "category": "touch-point",
    "touchPointId": 1,
    "reason": "matches touch-point 1 (apps/api/plane/settings/common.py) — fork edits allowed, append-only"
  },
  {
    "path": "apps/api/plane/ai_ext/models.py",
    "category": "custom-app",
    "touchPointId": null,
    "reason": "under apps/api/plane/ai_ext/ — fork-owned Django app"
  }
]
```

Verdict mapping:

- `fixtures/leak-core-column.diff` — changes `apps/api/plane/db/models/issue.py` → **core** → VIOLATION
- `fixtures/leak-outside-touchpoint.diff` — changes `apps/api/plane/app/views/issue/base.py` → **core** → VIOLATION
- `fixtures/clean.diff` — changes `apps/api/plane/settings/common.py` + `apps/api/plane/ai_ext/models.py` → **touch-point** + **custom-app** → PASS
