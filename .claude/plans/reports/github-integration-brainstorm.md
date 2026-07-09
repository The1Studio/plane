# Brainstorm — GitHub ↔ Plane Integration (`github_ext` fork app)

_Date: 2026-07-09 · Status: design APPROVED → ready for `/t1k:plan`_

## Problem

Link Plane work items to GitHub **branches, PRs, commits, and issues**. Today: 0 structured
links exist (migration carried none); only a manual one-way `plane-link-github-issue` skill
(shipped this session). Want real, (mostly) automatic dev-workflow linking + eventual issue sync.

## Decisions (user-confirmed)

| Decision               | Choice                                                                     |
| ---------------------- | -------------------------------------------------------------------------- |
| Scope                  | **Both, phased** — dev-workflow links first, issue sync later              |
| GitHub→Plane transport | **GitHub App + inbound webhook** (Plane is publicly reachable over HTTPS)  |
| Status automation      | **Global config + per-project override**                                   |
| P1 UI                  | **Reuse existing IssueLink Links panel** (backend-only MVP, zero frontend) |
| Design                 | **Approved — build the phased plan**                                       |

## Approaches evaluated

- **A. Webhook + reference linking (Linear-style)** ✅ chosen. Modern dev-panel pattern; greenfield (EE-only upstream).
- **B. Wire dormant `GithubIssueSync` models (bidirectional issue mirror).** Deferred to **P3** (issue-mirror only, no branch/PR; echo-loop risk).
- **C. Manual/agent-driven (no backend).** Rejected as primary (not real-time); the shipped skill already covers ad-hoc.
- **D. GitHub Actions push (no inbound webhook).** Kept as documented **fallback** for air-gapped installs; not needed (public HTTPS confirmed).

## Key research findings

- Upstream Plane's real GitHub integration = **closed-source EE "silo" worker** (not in CE/AGPL tree). CE ships only dormant issue-mirror models + a generic URL-title crawler → **greenfield build**.
- Dormant models (`GithubRepository/RepositorySync/IssueSync/CommentSync`) are **issue-mirroring**, not dev-workflow. Present in committed migration `0021_*` → tables exist, usable via ORM **no new migration** (must NOT add columns).
- Linear closing words to adopt: `close/fix/resolve/complete/implement` (+ tenses). Identifier `[A-Z]+-\d+`.

## Architecture (fork-isolated)

New app `apps/api/plane/github_ext/` (name TBD; scout used `github_link`). Wired via **2 touch-points only**:
`INSTALLED_APPS` (`settings/common.py:99`) + urls include (`urls.py:28`, BEFORE `plane.api.urls`). Celery auto-discovers `github_ext/bgtasks/*`. Frontend: none (reuse IssueLink). Env → `plane-deploy`.

### Fork-owned tables

`GithubInstallation` · `RepoProjectMap` (repo↔project disambiguation key) · `WorkItemGithubLink`
(`unique(issue,type,external_id)`) · `StateTransitionConfig` (scope=global|project, project overrides global)
· `WebhookDelivery` (`X-GitHub-Delivery` idempotency).

### Ingest flow (P0)

`POST /api/github/webhook/` → HMAC-256 verify **pre-parse** (constant-time) vs `Integration.webhook_secret`
→ dedup on delivery-id → **202 fast-ack** → Celery parse+dispatch.

## Seam map (concrete, from scout)

- **P1 link write**: `IssueLink.objects.create(project_id=, issue_id=, url=, metadata=)` → renders in existing Links UI. Resolve issue by `project + sequence_id` scoped by `RepoProjectMap`.
- **P2 state change — CRITICAL TRAP**: direct `issue.save()` does **NOT** fire IssueActivity / notifications / outbound webhook. **Fix: call Plane's internal API with a service `APIToken` (`X-Api-Key`, `is_service=True`)** → all side-effects free, zero core edit. (Alt: manually enqueue `issue_activity.delay` + `model_activity.delay`.) Done state = `State.objects.filter(project_id=, group="completed").first()`.
- **Celery**: `@shared_task(name="plane.github_ext.bgtasks.…", bind=True, max_retries=2)`; enqueue via `transaction.on_commit`. Precedent: `ai_ext/bgtasks/`.
- **Outbound (P3 / PR comments)**: GitHub App installation-token JWT flow = **all new code** (no scaffolding exists). Store creds in own table / `WorkspaceIntegration.config` (runtime JSON, no migration).

## Phases

| Phase                                 | Deliverable                                                                                                                                                   |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **P0** Ingest spine                   | App reg, webhook + HMAC, Celery dispatch, `GithubInstallation`+`RepoProjectMap`, delivery idempotency                                                         |
| **P1** Dev links (1-way, read-only)   | parse branch/PR/commit → `WorkItemGithubLink` + mirror to `IssueLink` (existing UI); dedup                                                                    |
| **P2** Status automation              | `StateTransitionConfig` (global+override); PR opened→In Progress, ready→In Review, merged+closing-word→Done; via service-token API call; bot-actor loop guard |
| **P3** Bidirectional issue sync (opt) | reuse dormant `GithubIssueSync`/`CommentSync`; provenance-stamp echo guard                                                                                    |
| Fallback                              | reusable GitHub Action → Plane API (air-gapped installs)                                                                                                      |

## Risks / mitigations

Echo loop → bot-actor guard · dup links → unique constraint · HMAC bypass → verify before parse ·
rate limits → installation tokens + async · mapping ambiguity → `RepoProjectMap`, never guess ·
**silent side-effect loss (trap #4)** → service-token API, not raw ORM · branch-naming discipline → devs must embed `PROJ-123`.

## Propagation (standing rule)

Config + link-query public endpoints → MCP tools (`plane-mcp-server`), SDK bindings
(`plane-node-sdk`/`plane-python-sdk`), `CLAUDE.md` custom-features entry. Track via sibling-repo issues.

## Open items for the plan

1. App name: `github_ext` vs `github_link` (scout used `github_link`).
2. Branch-naming convention doc for devs (`PROJ-123-slug`).
3. `RepoProjectMap` bootstrap: admin UI vs API vs auto-on-installation.
4. P3: reuse dormant core models vs fork tables (decide at P3).
5. Service-token vs manual-enqueue for P2 state change (lean service-token).

## Next step

`/t1k:plan` — phased implementation plan (P0→P3) with file ownership + tests, grounded in the seam map above.
