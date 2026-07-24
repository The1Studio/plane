# GitHub ↔ Plane — Branch & PR Naming Convention

_How to make your GitHub work auto-link to Plane work items._

The `github_ext` integration watches your repos' GitHub webhooks and links
**branches, PRs, and commits** to Plane work items automatically — **if** they
carry a Plane work-item identifier. This is opt-in by convention: name things
right and the links appear in the work item's **Links** panel; name them
anything else and nothing happens (no error, no link — silent by design).

## The identifier

A Plane work-item identifier is `PROJECT-NUMBER`, e.g. `PROJ-123`:

- `PROJ` = the **project identifier** (uppercase, shown on every work item).
- `123` = the work item's **sequence number**.

The integration matches the regex `\b[A-Z]+-\d+\b` and resolves it **only**
within the project the repo is mapped to. A mismatched prefix (an identifier for
a different project) is skipped — never cross-mapped.

## Branch names

Use: `PROJECT-NUMBER-short-slug`

```
PROJ-123-add-oauth-login
TIH-40-fix-crash-on-resume
```

- The identifier can appear anywhere matching `[A-Z]+-\d+`, but **prefix-first**
  is the recommended, readable convention.
- Unparseable branch names (no identifier) simply produce no link.

## Pull requests

Put the identifier in the **branch name**, the **PR title**, or the **PR body** —
any of them is picked up.

To also drive **status automation** (P2 — e.g. merge → Done), use a **closing
word** immediately before the identifier, Linear-style:

| Closing words (any tense)                                   |
| ----------------------------------------------------------- |
| `close` / `closes` / `closed` / `closing`                   |
| `fix` / `fixes` / `fixed` / `fixing`                        |
| `resolve` / `resolves` / `resolved` / `resolving`           |
| `complete` / `completes` / `completed` / `completing`       |
| `implement` / `implements` / `implemented` / `implementing` |

```
Title:  Fixes PROJ-123 — OAuth login
Body:   Resolves PROJ-124, refs PROJ-125
```

- `Fixes PROJ-123` → link **and** the closing-word flag (used by status
  automation to move the item to Done on merge).
- A bare `PROJ-125` (no closing word) → link only, no auto-transition.

## Commits

Reference the identifier in the commit message:

```
git commit -m "PROJ-123 wire up token refresh"
git commit -m "fixes PROJ-123: handle expired token"
```

A push with many commits mentioning the same identifier creates **one** commit
link (first mention wins) — no spam.

## Notes

- Matching is **case-sensitive** on the prefix: `proj-1` is ignored, `PROJ-1` is not.
- Links are one-way (GitHub → Plane) and render read-only in the existing Links panel.
- If a repo isn't mapped to a project yet, its events are dropped (logged) until
  an admin maps it.
