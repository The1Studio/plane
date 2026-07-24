# Phase P3 — Bidirectional Issue Sync (OPTIONAL)

**Goal:** mirror GitHub issues ↔ Plane work items (title/body/state/comments), reusing the
**dormant** core issue-mirror models. This phase is optional and deferrable; it is the highest-
risk phase (echo loops, provenance) and adds no dev-workflow value beyond P1/P2.

**Effort:** L · **Blocks:** — · **Blocked by:** P0, P1, P2.

---

## Decision at start of P3 (do NOT resolve earlier)

**Dormant core models vs new fork tables.** Verified dormant models exist and are importable
(tables shipped in `db/migrations/0021_auto_20230223_0104.py`):

- `GithubRepository`, `GithubRepositorySync`, `GithubIssueSync`, `GithubCommentSync`
  (`db/models/integration/github.py:14-73`).

| Option                                                                        | Pros                                                 | Cons                                                                                          |
| ----------------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Reuse dormant models** (ORM only, **no new migration**, **no new columns**) | Zero schema churn; tables already exist; rebase-safe | Fixed shape; must NOT add columns (FORK.md); provenance must live in existing JSON/`metadata` |
| **New fork tables** in `github_ext`                                           | Full control of shape (provenance, sync cursors)     | More schema; but still app-local + rebase-safe                                                |

**Recommendation (flag as decided-at-P3):** reuse dormant `GithubIssueSync` / `GithubCommentSync`
via ORM for the mirror bookkeeping, storing provenance in their existing JSON fields; add a
`github_ext`-owned table ONLY if a needed field has no home. Confirm with a 1-paragraph memo at
P3 kickoff before writing code.

---

## Deliverables / file ownership

| File                                    | Purpose                                                                                                      |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `github_ext/services/issue_sync.py`     | GitHub issue ↔ Plane issue field mapping + provenance stamp.                                                 |
| `github_ext/bgtasks/issue_sync_task.py` | `@shared_task` for `issues`/`issue_comment` inbound + outbound (installation-token JWT flow — all-new code). |
| `github_ext/tests/test_issue_sync.py`   | Round-trip + echo-guard tests.                                                                               |
| (decision memo)                         | Dormant-model-reuse vs fork-table, recorded in the PR description.                                           |

---

## Concrete steps

1. **Kickoff memo** — resolve the model-reuse decision above.
2. **Inbound** (`issues`/`issue_comment` → Plane): create/update the Plane work item via the
   **service-token internal API** (same trap #4 discipline as P2 — never raw ORM for the issue
   itself). Record the GitHub↔Plane mapping + a **provenance stamp** (`source=github`,
   `external_id`, `synced_at`) in the sync model's JSON.
3. **Outbound** (Plane → GitHub): installation-token JWT flow (App JWT → installation access
   token → REST call). **All-new code** — no scaffolding exists. Sign/store nothing plaintext
   beyond token TTL. Mirror outbound signing discipline from `bgtasks/webhook_task.py:316-322`.
4. **Echo guard (provenance):** before writing in either direction, check the provenance stamp
   — an update whose `source` == the side we're about to write to is a reflection, dropped.
   This is the P2 bot-actor guard generalized to two-way content sync.

---

## Risk assessment (P3-local)

| Risk                                                        | L   | I   | Score         | Mitigation                                                                                                                       |
| ----------------------------------------------------------- | --- | --- | ------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Infinite echo loop** (A writes B writes A …)              | 4   | 5   | **20 (HIGH)** | Provenance stamp on every write; drop reflections; loop-detection test is a merge gate. **Mandatory before any outbound write.** |
| Trap #4 on inbound issue create/update                      | 3   | 5   | **15 (HIGH)** | Service-token internal API for the Plane-side write; never raw ORM.                                                              |
| Adding a column to a core/dormant model (FORK.md violation) | 2   | 5   | 10            | Reuse existing JSON fields for provenance; new field → `github_ext` table, never a core column.                                  |
| Installation-token leak                                     | 2   | 5   | 10            | Short-lived tokens, never persisted beyond TTL, never logged.                                                                    |
| Field-mapping drift (state/label semantics differ)          | 3   | 2   | 6             | Explicit mapping table; unmapped → skip + log.                                                                                   |

**Two HIGH risks (echo loop = 20, trap #4 = 15).** Both gated: the loop-detection test and the
`IssueActivity`-created assertion are merge blockers for P3.

---

## Test list

- Inbound GitHub issue → Plane work item created via service token; `IssueActivity` row exists.
- **Echo guard:** a Plane-originated update flowing back inbound → dropped (no duplicate write).
- Outbound Plane → GitHub uses a fresh installation token; provenance stamped.
- Comment round-trip: GitHub comment → Plane comment, no reflection back.
- No core/dormant model column added (`makemigrations --check` clean).

## Gates

- `plane-isolation-audit` clean (dormant models reused via ORM — no core edit; new tables, if
  any, are `github_ext`-owned).
- `makemigrations --check --dry-run` — **must be clean** (reusing dormant tables adds no
  migration; a new fork table adds a `github_ext` migration only).
- `python manage.py check`.
- `pytest plane/github_ext`.

## Rollback

Sync bookkeeping is additive (dormant tables were empty). Disable = stop enqueuing
`issue_sync_task`. If a fork table was added, `migrate github_ext <prev>` removes it cleanly.
Because dormant tables already existed, no core schema is touched.
