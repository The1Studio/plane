---
name: plane-link-github-issue
description: Link a GitHub issue to a Plane work item (one-way reference) by attaching the issue URL as a link on the Plane item. Use for "link this GitHub issue to Plane", "attach the GH issue to the work item", "add the issue link to Plane", "connect issue #N to a Plane task".
keywords: [github, issue, plane, link, work-item, reference, attach, cross-link]
metadata:
  author: the1studio
  version: "1.0.0"
---

# plane-link-github-issue

Attach a GitHub issue to a Plane work item as a **one-way reference link** — the GitHub
issue URL shows up under the Plane item's **Links**. This is a lightweight cross-reference,
**not** a two-way sync (status/comments are not mirrored; that would need the dormant
`GithubIssueSync` tables wired into a fork app — out of scope here).

**Preferred path:** the `plane-mcp-server` tool `create_work_item_link` when that MCP is
registered. **Fallback (default):** the bundled `scripts/link-issue.sh`, which POSTs to
Plane's public REST API — use this whenever the Plane MCP is not connected in the session.

**Policy citations (read before acting):**

- `rules/plane-fork-discipline.md` — this skill is a **new isolated skill file only**; it
  makes NO Plane core edits and adds NO columns. Never edit Plane core to build linking.
- `rules/security.md` — `PLANE_API_TOKEN` is a secret: read from env, never echo/commit it.
- `rules/always-ask-on-unresolved.md` — if the target work item is ambiguous, ask; don't guess.

---

## When to Use

Invoke when the user wants to associate a GitHub issue with a specific Plane work item, e.g.:

- "Link GitHub issue The1Studio/plane#7 to this Plane task."
- "Attach that GH issue URL to the work item in Plane."
- "Cross-reference issue #6 with the migration item in Plane."

Do NOT use for: two-way GitHub↔Plane sync (feature-scale; scaffold a fork app instead),
or linking a Plane page/module (this skill targets **work items / issues** only).

---

## Inputs you need

| Input                                                       | How to get it                                                                                                                                                                                                |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| GitHub issue **URL** + **title**                            | GitHub MCP `issue_read` / `list_issues`, or the user pastes the URL. Always pass `-R The1Studio/<repo>` — sibling repos default to the public upstream (see `[[plane-sibling-repos-gh-defaults-upstream]]`). |
| Plane **project_id** (UUID)                                 | From a Plane work-item URL: `…/projects/<project_id>/issues/<work_item_id>`, or Plane MCP `list_work_items`.                                                                                                 |
| Plane **work_item_id** (UUID)                               | Same URL, or MCP `search` by name.                                                                                                                                                                           |
| `PLANE_BASE_URL`, `PLANE_WORKSPACE_SLUG`, `PLANE_API_TOKEN` | Instance base URL, workspace slug, and a personal API token (Plane → Settings → API tokens). Token is a secret.                                                                                              |

**Parsing a Plane work-item URL** (the fastest way to get both UUIDs):
`https://<base>/<workspace>/projects/<PROJECT_UUID>/issues/<WORK_ITEM_UUID>`

---

## Workflow

1. **Resolve the GitHub issue.** If given an issue number, call GitHub MCP `issue_read`
   with `-R The1Studio/<repo>` to fetch the canonical `html_url` and `title`. If given a
   URL directly, use it verbatim.
2. **Resolve the Plane work item.** Parse `project_id` + `work_item_id` from a Plane
   work-item URL, or use Plane MCP `list_work_items` / `search`. If more than one candidate
   matches an ambiguous name → **AskUserQuestion**, never guess.
3. **Confirm before writing** (this mutates Plane state). State: "Linking `<gh-url>` →
   Plane work item `<id>` (project `<id>`). Proceed?" Skip only if the user already gave an
   unambiguous, explicit instruction this turn.
4. **Create the link:**
   - **If Plane MCP registered:** call `create_work_item_link(project_id, work_item_id, url)`.
     (The MCP tool sends URL only — no title.)
   - **Else (default):** run the helper, which also sets a human-readable `title`:
     ```bash
     PLANE_BASE_URL=https://plane.the1studio.org \
     PLANE_WORKSPACE_SLUG=the1studio \
     PLANE_API_TOKEN=<token> \
     bash .claude/skills/plane-link-github-issue/scripts/link-issue.sh \
       --project <PROJECT_UUID> \
       --work-item <WORK_ITEM_UUID> \
       --url 'https://github.com/The1Studio/plane/issues/7' \
       --title 'GH#7 — ledger key collision'
     ```
5. **Verify.** The helper prints the created link JSON (id + url) on HTTP 2xx and exits
   non-zero on any error. Report the link id back to the user.
6. **(Optional) reverse pointer.** If the user wants discoverability from GitHub too, offer
   to add a GitHub issue comment linking back to the Plane item via GitHub MCP
   `add_issue_comment` (`-R The1Studio/<repo>`). Ask first — it posts publicly to GitHub.

---

## Endpoint reference (fallback path)

`POST /api/v1/workspaces/{slug}/projects/{project_id}/issues/{issue_id}/links/`
Auth header `X-API-Key: <PLANE_API_TOKEN>`; body `{"url": "...", "title": "..."}`.
The `work-items/…/links/` path is an accepted alias for `issues/…/links/`.

`IssueLink` model fields: `url` (required), `title` (optional), `metadata` (JSON, unused here).

---

## Gotchas

- **Plane MCP absent by default** — most sessions here have `github` + `clickup` MCPs but
  NOT a `plane` MCP. Default to the helper script; only use `create_work_item_link` after
  confirming a `plane` server is registered.
- **`X-API-Key`, not Bearer** — Plane's public API uses the `X-API-Key` header. A `Bearer`
  token returns 401.
- **UUIDs, not sequence ids** — the API wants the work item's UUID (`work_item_id`), not the
  human `PROJ-123` sequence id. Parse the UUID from the work-item URL.
- **Idempotency** — Plane does not dedupe links by URL; running twice creates two identical
  links. Check existing links (`GET …/links/`) first if re-linking is possible.
- **Sibling-repo gh default** — `gh`/GitHub-MCP calls without an explicit repo hit the public
  upstream `makeplane/*`, not `The1Studio/*`. Always pass the repo. See
  `[[plane-sibling-repos-gh-defaults-upstream]]`.

---

## Downstream propagation

Per `CLAUDE.md` standing rule: this skill uses the **existing** public link endpoint and the
existing `create_work_item_link` MCP tool — no new Plane endpoint/field is introduced, so no
MCP/SDK propagation is required. If a future version writes the dormant `GithubIssueSync`
tables (two-way sync), that IS a new feature and must be scaffolded as a fork app +
propagated via `plane-propagate`.
