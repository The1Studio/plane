# Plan — GitHub ↔ Plane Integration (`github_ext` fork app)

Brainstorm: `.claude/plans/reports/github-integration-brainstorm.md` (design APPROVED 2026-07-09).
Per-phase detail files: `.claude/plans/github-integration/phase-P{0,1,2,3}.md`.
Approach A (Linear-style webhook + reference linking), greenfield build, fork-isolated new
Django app `apps/api/plane/github_ext/`. Frontend: none (reuse the existing `IssueLink` Links
panel). Only the **2 documented touch-points** may change in core.

---

## 0. Locked decisions (user-confirmed — do NOT re-litigate)

- **App name:** `github_ext` → `apps/api/plane/github_ext/`, label `github_ext`.
- **P2 state change:** call Plane's **internal API with a service `APIToken`**
  (`is_service=True`, header `X-Api-Key`) — NOT raw ORM `issue.save()`. Raw save silently
  skips `IssueActivity` / notifications / outbound webhook (**trap #4**). The API path gets
  every side-effect free with zero core edit. Verified: `APIToken.is_service`
  (`db/models/api.py:38`); `X-Api-Key` validated at
  `api/middleware/api_authentication.py:24-52`; `is_service=True` → `ServiceTokenRateThrottle`
  (`api/views/base.py:64-73`).
- **`RepoProjectMap` bootstrap:** auto-seed on GitHub App `installation` /
  `installation_repositories` webhook (repo → inferred project), then editable via API/MCP.
  **No admin UI** (backend-only MVP).
- **Plan depth:** standard (single planner). **Branch-naming:** ship a `PROJ-123-slug`
  convention doc as a **P1 deliverable**.
- **P3 model-reuse** (dormant `GithubIssueSync`/`GithubCommentSync` vs new fork tables):
  **decided at P3**, does not block P0–P2.

---

## 1. Architecture at a glance

```
GitHub  ──(webhook, HMAC-SHA256)──►  POST /api/github/webhook/   [github_ext, P0]
                                       │  verify sig PRE-parse (constant-time) vs
                                       │  Integration.webhook_secret
                                       │  dedup on X-GitHub-Delivery (WebhookDelivery)
                                       │  202 fast-ack
                                       ▼
                             Celery @shared_task  (autodiscover, no core edit)
                             plane.github_ext.bgtasks.dispatch.route_event
                                       │
              ┌────────────────────────┼─────────────────────────────┐
              ▼                        ▼                              ▼
   P1: parse refs → link      P2: state transition           P3 (opt): issue mirror
   WorkItemGithubLink         via service-token API call      dormant models / echo guard
   + mirror IssueLink         (StateTransitionConfig)
```

**Fork-owned tables** (all in `github_ext/migrations/0001_initial.py`, own app, no core columns):
`GithubInstallation` · `RepoProjectMap` · `WorkItemGithubLink` (`unique(issue,type,external_id)`)
· `StateTransitionConfig` (`scope ∈ {global, project}`) · `WebhookDelivery`
(`unique(delivery_id)` idempotency).

**HMAC secret slot:** `Integration.webhook_secret` (`db/models/integration/base.py`) — reuse
the dormant `Integration` row (`provider="github"`); no new column. Outbound signing pattern to
mirror: `bgtasks/webhook_task.py:316-322` (`hmac.new(secret, body, sha256).hexdigest()` →
header). We **verify inbound** with the same primitive **before** JSON parse, constant-time
(`hmac.compare_digest`).

**GitHub App credentials** (App ID, private key, webhook secret) are **secrets** — stored in
`plane-deploy` env (`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`), read
via `os.environ.get` inside `github_ext`. Runtime per-workspace config (installation id →
workspace) lives in `GithubInstallation` / `WorkspaceIntegration.config` JSON. **Never commit
the private key or webhook secret.**

**Least-privilege GitHub App permissions:** Contents `read`, Pull requests `read/write`,
Issues `read/write`, Metadata `read`, Checks `read`. Subscribed events: `push`,
`pull_request`, `issues`, `issue_comment`, `installation`, `installation_repositories`.

---

## 2. Touch-points changed in core (EXACTLY two — FORK.md tp1 + tp2)

| #   | File                                | Edit (append-only)                                                                                                                                                                                                                                               |
| --- | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `apps/api/plane/settings/common.py` | append `"plane.github_ext",` to `INSTALLED_APPS` after `"plane.workload",` (~:99). **Optional:** append `"plane.github_ext.bgtasks.*": {"queue": "..."}` to `CELERY_TASK_ROUTES` (~:526) — default is to reuse the default queue (no route line needed for MVP). |
| 2   | `apps/api/plane/urls.py`            | append `path("api/", include("plane.github_ext.urls")),` (~:28). Place it BEFORE `path("api/v1/", include("plane.api.urls"))` per the documented ordering rule at `urls.py:21`.                                                                                  |

Celery: **zero edit** — `app.autodiscover_tasks()` (`celery.py:101`) already scans
`github_ext/bgtasks/*`. Any conflict outside these two files on rebase = a leak → `git rebase
--abort` and relocate.

---

## 3. Phase summary

| Phase  | Name                                | Scope                                                                                                                                                        | Effort | Blocked by |
| ------ | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ | ---------- |
| **P0** | Ingest spine                        | App reg + models + webhook endpoint (HMAC pre-parse verify, constant-time) + delivery idempotency + Celery fast-ack dispatch + `RepoProjectMap` auto-seed    | **L**  | —          |
| **P1** | Dev-workflow links (read-only)      | parse `[A-Z]+-\d+` from branch/PR/commit scoped by `RepoProjectMap`; closing-word detection; `WorkItemGithubLink` + mirror to `IssueLink`; branch-naming doc | **M**  | P0         |
| **P2** | Status automation                   | `StateTransitionConfig` (global + project override); PR lifecycle → state via **service-token API**; bot-actor loop guard                                    | **M**  | P0, P1     |
| **P3** | Bidirectional issue sync (OPTIONAL) | reuse dormant `GithubIssueSync`/`GithubCommentSync`; provenance echo guard                                                                                   | **L**  | P0–P2      |
| **P4** | Propagation (standing rule)         | MCP tools + SDK bindings + docs + `CLAUDE.md` entry — via sibling-repo issues                                                                                | **S**  | P1, P2     |

**Critical path:** P0 → P1 → P2 → P4. P3 is optional and parallel-deferrable.

---

## 4. Dependency graph

- **P0 blocks everything** — no event ingress, no models, until the spine exists.
- **P1 blocked by P0** (needs `RepoProjectMap` + dispatched events).
- **P2 blocked by P0 + P1** (state transition keys off the same parsed link + closing word).
- **P3 blocked by P0–P2** (reuses ingest + dispatch; decided at start of P3).
- **P4 blocked by P1 + P2** (propagates the endpoints/behaviors those phases add).
- **Parallel-safe:** P1 link-parsing logic and P2 `StateTransitionConfig` model/CRUD can be
  authored concurrently once P0 lands (different files), but P2's transition trigger consumes
  P1's parse output — sequence the wiring.

---

## 5. Cross-phase risk assessment (see per-phase files for phase-local risks)

| Risk                                                                                           | L (1-5) | I (1-5) | Score         | Mitigation                                                                                                                                                          |
| ---------------------------------------------------------------------------------------------- | ------- | ------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **HMAC bypass / forged webhook**                                                               | 3       | 5       | **15 (HIGH)** | Verify signature **before** JSON parse, `hmac.compare_digest` (constant-time), reject 401 on mismatch. Secret from env, never committed. Gate in P0 tests.          |
| **Silent side-effect loss (trap #4)** — state change via raw ORM skips activity/notify/webhook | 3       | 5       | **15 (HIGH)** | P2 uses service-token internal API call ONLY; a code-review gate forbids `issue.save()` in `github_ext`. Test asserts `IssueActivity` row created after transition. |
| **Echo loop** — our API-driven state change emits a webhook GitHub echoes back                 | 3       | 4       | 12            | Bot-actor guard: transitions run as a dedicated bot user; dispatch drops events whose actor == our bot / provenance-stamped.                                        |
| **Duplicate links** on webhook redelivery                                                      | 4       | 2       | 8             | `WorkItemGithubLink unique(issue,type,external_id)` + `WebhookDelivery unique(delivery_id)` idempotency.                                                            |
| **Repo→project mapping ambiguity**                                                             | 3       | 3       | 9             | Never guess: resolve strictly via `RepoProjectMap`; unmapped repo → log + drop, never fall back to a default project.                                               |
| **GitHub API rate limits** on outbound                                                         | 2       | 3       | 6             | Installation tokens (per-install quota) + all outbound in Celery with `max_retries=2`, exponential backoff.                                                         |
| **Rebase leak** (edit escapes the 2 touch-points)                                              | 2       | 4       | 8             | `plane-isolation-audit` gate every phase; CI `company-main-ci.yml`.                                                                                                 |
| **Migration drift** (new app migration not checked in)                                         | 2       | 3       | 6             | `makemigrations --check --dry-run` gate every phase.                                                                                                                |

**Risk ≥ 15 → mitigation mandatory before that phase starts.** Both HIGH risks are gated inside
P0 (HMAC) and P2 (trap #4) respectively.

---

## 6. Per-phase gates (run inside the `api` container per CLAUDE.md)

Every phase MUST pass, in order, before it is called done:

1. **Isolation:** `plane-isolation-audit` clean — only tp1 + tp2 changed in core.
2. **Migration:** `docker exec api sh -c 'cd /code && python manage.py makemigrations --check --dry-run'` → no missing migration.
3. **System check:** `docker exec api sh -c 'cd /code && python manage.py check'` → 0 issues.
4. **Tests:** `docker exec api sh -c 'cd /code && pytest plane/github_ext'` → green (copy in `pytest.ini` + `plane/github_ext/` first if the baked image predates the change, per CLAUDE.md).

> Container note (memory): serialize pytest in the shared `api` container — concurrent runs
> corrupt `test_plane` teardown. Never run two `github_ext` suites at once.

---

## 7. Security checklist (applies across all phases)

- [ ] HMAC-SHA256 verify **before** `json.loads`, constant-time compare, 401 on mismatch.
- [ ] Webhook secret + App private key: env/`plane-deploy` only, never committed; audited by
      `git grep -iE 'PRIVATE_KEY|WEBHOOK_SECRET'`.
- [ ] GitHub App least-privilege perms (Contents r, PRs r/w, Issues r/w, Metadata r, Checks r).
- [ ] Service `APIToken` for P2 is scoped to a bot user, workspace-bound, `is_service=True`.
- [ ] No secret in `WebhookDelivery` payload logs (store headers + event type, redact tokens).
- [ ] Installation tokens are short-lived (JWT → installation token), never persisted plaintext
      beyond their TTL.

---

## 8. Definition of Done (whole feature)

Backend: `pytest plane/github_ext` green · `manage.py check` clean · `makemigrations --check`
clean (`company-main-ci.yml` gate) · isolation audit clean (only tp1+tp2 touched). P1 links
render in the existing IssueLink UI with zero frontend code. P2 transitions produce
`IssueActivity` rows (proves the service-token path fired all side-effects). Branch-naming doc
shipped. Propagation issues filed on `plane-mcp-server`, `plane-node-sdk`, `plane-python-sdk`;
`CLAUDE.md` "Custom features" updated. No core edits outside the 2 documented touch-points.

---

## 9. File ownership (exclusive per phase)

| Phase | Files                                                                                                                                                                                                                                                                                                                                |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| P0    | `github_ext/{__init__,apps,models,urls,signals}.py`, `github_ext/migrations/0001_initial.py`, `github_ext/webhook/{__init__,verify,views}.py`, `github_ext/bgtasks/{__init__,dispatch}.py`, `github_ext/services/{installation,repo_map}.py`, `github_ext/tests/test_webhook.py` · **core:** tp1 `settings/common.py`, tp2 `urls.py` |
| P1    | `github_ext/parsing/{refs,closing_words}.py`, `github_ext/bgtasks/link_task.py`, `github_ext/services/link_writer.py`, `github_ext/tests/{test_parsing,test_links}.py`, `docs/github-branch-naming.md`                                                                                                                               |
| P2    | `github_ext/models.py` (+`StateTransitionConfig` — same 0001 or 0002), `github_ext/services/state_transition.py`, `github_ext/bgtasks/transition_task.py`, `github_ext/views/config.py`, `github_ext/tests/{test_transition,test_config}.py`                                                                                         |
| P3    | `github_ext/services/issue_sync.py`, `github_ext/bgtasks/issue_sync_task.py`, `github_ext/tests/test_issue_sync.py` (+ decision memo on dormant-model reuse)                                                                                                                                                                         |
| P4    | sibling repos via **issues only** (`plane-mcp-server`, `plane-node-sdk`, `plane-python-sdk`); this repo: `CLAUDE.md`                                                                                                                                                                                                                 |

---

## 10. Timeline

| Phase                | Effort          | Notes                                                                                                        |
| -------------------- | --------------- | ------------------------------------------------------------------------------------------------------------ |
| P0 Ingest spine      | L               | Greenfield: models + migration + HMAC verify + Celery dispatch + App reg. Both HIGH risks (HMAC) gated here. |
| P1 Dev links         | M               | Pure parsing + link write; reuses IssueLink UI (zero frontend).                                              |
| P2 Status automation | M               | Service-token API path (trap #4 gate) + config CRUD + loop guard.                                            |
| P3 Issue sync (opt)  | L               | Optional; model-reuse decision at start. Can defer indefinitely.                                             |
| P4 Propagation       | S               | Issues on 3 sibling repos + CLAUDE.md line.                                                                  |
| **Total**            | **L+M+M(+L)+S** | **Critical path: P0 → P1 → P2 → P4.** P3 optional/parallel-deferred.                                         |
