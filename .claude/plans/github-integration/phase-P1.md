# Phase P1 — Dev-Workflow Links (read-only, one-way)

**Goal:** from `push` / `pull_request` events, parse Plane identifiers out of branch refs, PR
titles/bodies, and commit messages (scoped by `RepoProjectMap`), then write
`WorkItemGithubLink` rows and **mirror** them into the existing `IssueLink` so they render in
Plane's Links panel with **zero frontend code**.

**Effort:** M · **Blocks:** P2, P4 · **Blocked by:** P0.

---

## Deliverables / file ownership

| File                                  | Purpose                                                                                                                                                                              |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `github_ext/parsing/refs.py`          | `extract_identifiers(text) -> list[str]` via regex `\b[A-Z]+-\d+\b`; dedup, upper-case.                                                                                              |
| `github_ext/parsing/closing_words.py` | `find_closing_links(text) -> list[(word, identifier)]`; Linear closing words `close/fix/resolve/complete/implement` (+ `-s/-es/-ed/-ing` tenses), case-insensitive, word-boundaried. |
| `github_ext/bgtasks/link_task.py`     | `@shared_task` consuming dispatched `push`/`pull_request` payloads → parse → resolve issue → write link.                                                                             |
| `github_ext/services/link_writer.py`  | Resolve `Issue` by `project + sequence_id` (scoped by `RepoProjectMap`); create `WorkItemGithubLink` + mirror `IssueLink`.                                                           |
| `github_ext/tests/test_parsing.py`    | Pure-function parser tests (no DB).                                                                                                                                                  |
| `github_ext/tests/test_links.py`      | DB tests: link write, dedup, IssueLink mirror, scope resolution.                                                                                                                     |
| `docs/github-branch-naming.md`        | Dev convention doc: `PROJ-123-slug` branch naming + closing-word cheatsheet.                                                                                                         |

---

## Concrete steps

1. **Identifier parse (`refs.py`):** regex `\b[A-Z]+-\d+\b`. The `[A-Z]+` maps to a Plane
   **project identifier** and `\d+` to `Issue.sequence_id`. Return normalized, de-duplicated.
2. **Closing-word parse (`closing_words.py`):** detect `(close|fix|resolve|complete|implement)`
   with tense suffixes immediately preceding an identifier (Linear-style), e.g.
   `fixes PROJ-12`. Return `[(closing_word, identifier)]` — consumed by **P2** for the
   merged→Done transition; P1 only records the flag on the link metadata.
3. **Scope resolution (`link_writer.py`):** given a webhook repo → look up `RepoProjectMap` for
   `(installation, repo_full_name)` → get `project`. **Resolve issue by `project_id +
sequence_id`** (the `[A-Z]+` prefix must match the project identifier; mismatch → skip, log,
   never cross-map). Unmapped repo → drop + log (no guess).
4. **Link write:** `WorkItemGithubLink.objects.get_or_create(issue=, type=, external_id=,
defaults={url, project, metadata})` — the `unique(issue,type,external_id)` constraint makes
   redelivery idempotent. `type ∈ {branch, pr, commit}` in P1.
5. **Mirror to IssueLink** (the zero-frontend trick): `IssueLink.objects.get_or_create(
project_id=, issue_id=, url=, defaults={metadata})` → renders in the existing Links UI
   (`app/views/issue/link.py:24`; model `db/models/issue.py`). Guard against duplicate
   `IssueLink` rows on the same `(issue, url)`.
   - **Decision (record in code comment):** do NOT invoke the core `IssueLinkViewSet` (needs a
     request/actor); create the `IssueLink` row directly — it is a **display mirror**, not a
     state-changing work-item mutation, so trap #4 does NOT apply here (no activity/notify is
     expected for a link row). Keep the write inside the Celery task, idempotent.
6. **Branch-naming doc (`docs/github-branch-naming.md`):** `PROJ-123-short-slug` branch
   convention; PR title/body closing-word cheatsheet; note that unparseable branches simply
   produce no link (silent, by design). Link it from `CLAUDE.md` in P4.

---

## Risk assessment (P1-local)

| Risk                                                                       | L   | I   | Score | Mitigation                                                                                                        |
| -------------------------------------------------------------------------- | --- | --- | ----- | ----------------------------------------------------------------------------------------------------------------- |
| False-positive identifier match (`ABC-123` in prose that isn't a Plane id) | 3   | 2   | 6     | Require the `[A-Z]+` prefix to match a real project identifier in the mapped project; unresolved → skip silently. |
| Duplicate `IssueLink` rows on redelivery                                   | 3   | 2   | 6     | `get_or_create` on `(issue, url)` for the mirror + `WorkItemGithubLink` unique constraint.                        |
| Cross-project mis-link (repo maps to project A, id belongs to B)           | 2   | 4   | 8     | Resolve strictly within the mapped project's `sequence_id` space; prefix mismatch → skip.                         |
| Commit-message spam (100 commits in one push → 100 link tasks)             | 3   | 2   | 6     | Dedup identifiers per push before writing; one task per delivery, batch the writes.                               |
| Parser regex catastrophic backtracking                                     | 1   | 3   | 3     | Simple linear regex `\b[A-Z]+-\d+\b`; unit-tested on long inputs.                                                 |

No P1 risk ≥ 15.

---

## Test list

**`test_parsing.py` (pure, no DB):**

- `extract_identifiers` finds `PROJ-1`, multiple, dedups, ignores lowercase `proj-1`.
- `find_closing_links` matches all 5 words + tenses (`fixes`, `resolved`, `implementing`);
  ignores a closing word with no adjacent identifier.

**`test_links.py` (DB, in `api` container):**

- `push` on a mapped repo with `PROJ-3` in branch → `WorkItemGithubLink(type=branch)` +
  mirrored `IssueLink` created.
- Redelivery of same event → no duplicate link (constraint holds).
- Unmapped repo → no link, logged.
- Identifier for a project the repo isn't mapped to → skipped.
- PR title `Fixes PROJ-4` → link of `type=pr` with closing-word flag in metadata.

## Gates

- `plane-isolation-audit` clean (P1 adds `docs/github-branch-naming.md` — allowed, not core
  code; no new core touch-point).
- `makemigrations --check --dry-run` (WorkItemGithubLink already in P0's 0001 — expect no new migration).
- `python manage.py check`.
- `pytest plane/github_ext`.

## Rollback

Link writes are additive rows; delete via `WorkItemGithubLink`/`IssueLink` cleanup query. No
schema change beyond P0. Disabling P1 = stop enqueuing `link_task` in dispatch.
