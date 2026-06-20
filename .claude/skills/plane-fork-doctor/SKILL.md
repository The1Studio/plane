---
name: plane-fork-doctor
description: Aggregate fork health into one report — tags-behind-upstream, isolation status, migration check, rerere health, convention drift, propagation backlog. Use for "fork health", "fork doctor", "is the fork healthy", "check fork status".
keywords: [fork, doctor, health, upstream, isolation, drift, rerere, propagation]
metadata:
  author: the1studio
  version: "1.0.0"
---

# plane-fork-doctor

Read-only aggregate health report for the `company-main` fork. Collects 7 signals
from existing tools and skills — no logic is duplicated here. Emits a single
GREEN/YELLOW/RED verdict table.

No hard gates. Runs to completion regardless of individual check results and reports
all findings together.

SSOT for convention rules: `docs/FORK.md`.
Convention data mirror (JSON block): `.claude/skills/_shared/references/fork-convention.md`.

---

## When to Use

- "Fork health" — quick pre-rebase sanity check
- Before opening a PR to `company-main`
- After a merge/rebase, to confirm the fork is in a clean state
- Periodic maintenance (monthly rebase cadence)
- When onboarding a new contributor who needs a fork-state overview

---

## Activation

Trigger phrases (any of these should activate this skill):

- "fork health"
- "fork doctor"
- "is the fork healthy"
- "check fork status"
- "tags behind upstream"
- "fork health report"

---

## Checks

Run all 7 checks in the order listed. Each check delegates to an existing signal —
no audit/rebase/propagation logic is reimplemented here.

| #   | Check                        | Source / command                                                                                                                                                                                                                                             | YELLOW threshold                                           | RED threshold                               |
| --- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------- |
| 1   | **Tags behind upstream**     | `git fetch upstream --tags --dry-run` then compare `git tag -l 'v*' \| sort -V \| tail -1` vs `git tag -l 'company-v*' \| sort -V \| tail -1` to derive the adopted upstream base                                                                            | 1–2 tags behind latest upstream `v*`                       | >2 tags behind                              |
| 2   | **Isolation status**         | Delegate to `plane-isolation-audit` skill over the working tree (`git diff --name-only HEAD`); surface its PASS/FAIL verdict                                                                                                                                 | Any append-only warning (non-violation)                    | Any VIOLATION                               |
| 3   | **Migration check**          | `cd apps/api && python manage.py makemigrations --check --dry-run` (mirrors CI gate in `company-main-ci.yml`)                                                                                                                                                | —                                                          | Non-zero exit / pending migrations detected |
| 4   | **Django system check**      | `cd apps/api && python manage.py check` (mirrors CI gate)                                                                                                                                                                                                    | —                                                          | Non-zero exit / any error reported          |
| 5   | **rerere-cache health**      | `git config --get rerere.enabled` must equal `true`; `.git/rr-cache/` directory must exist (populated = prior conflicts were recorded)                                                                                                                       | `rerere.enabled=true` but `.git/rr-cache/` empty or absent | `rerere.enabled` not set or `false`         |
| 6   | **Classifier↔FORK.md drift** | Parse the JSON `touchPoints[*].paths` block from `.claude/skills/_shared/references/fork-convention.md` and diff against the file list in `docs/FORK.md` §The complete 6 core touch-point inventory table. Report any path present in one but not the other. | —                                                          | Any mismatch                                |
| 7   | **Propagation backlog**      | Count open (unchecked) entries in `.claude/plane-propagation-queue.md` (lines beginning with `- [ ]`). File absent = 0 open items.                                                                                                                           | 1–3 open items                                             | >3 open items                               |

---

## Output

Emit a single Markdown health table followed by an overall verdict line.

```
### Fork Health Report — <timestamp or "as of HEAD">

| Check | Status | Detail |
|-------|--------|--------|
| Tags behind upstream    | GREEN  | company-v1.3.1-1 adopts v1.3.1; latest upstream is v1.3.1 — up to date |
| Isolation status        | GREEN  | PASS — no violations in working tree |
| Migration check         | GREEN  | No pending migrations |
| Django system check     | GREEN  | System check identified no issues (0 silenced) |
| rerere-cache health     | GREEN  | rerere.enabled=true; .git/rr-cache/ present with N entries |
| Classifier↔FORK.md drift| GREEN  | Touch-point paths match (6/6) |
| Propagation backlog     | YELLOW | 2 open items in plane-propagation-queue.md |

**Overall: YELLOW** — 1 check(s) in YELLOW, 0 in RED.
Action required: address YELLOW/RED checks before next rebase.
```

**Aggregation rules:**

- Any RED check → overall **RED** (fix before rebase/PR).
- No RED but any YELLOW → overall **YELLOW** (address soon).
- All GREEN → overall **GREEN** (fork is healthy).

**When a check cannot run** (e.g., `python manage.py` is not available outside the Docker
container, or `upstream` remote is not configured): mark that check as `SKIP — <reason>`
and note it in the detail column. SKIP does not count as RED or YELLOW for the overall verdict,
but list all SKIPs at the bottom so the operator knows what was not verified.

**Do not re-run `plane-rebase` or write any files.** This skill is read-only and
produces no side effects. To action the findings, use:

- Tags behind → `plane-rebase` skill
- Isolation violations → `plane-isolation-audit` skill for per-file guidance
- Propagation backlog → `plane-propagate` skill
- Migration failures → resolve conflicts then rerun `makemigrations`
