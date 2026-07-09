# Phase P0 — Ingest Spine

**Goal:** stand up the fork app, its tables, and a verified, idempotent, fast-acking webhook
endpoint that dispatches parsed events to Celery. No linking or state logic yet — P0 proves the
pipe is secure and rebase-safe.

**Effort:** L · **Blocks:** P1, P2, P3 · **Blocked by:** none.

---

## Deliverables / file ownership

| File                                             | Purpose                                                                                                                                                                 |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `github_ext/__init__.py`, `apps.py`              | App config (label `github_ext`; `ready()` imports `signals` guarded — mirror `ai_ext/apps.py:15-28`).                                                                   |
| `github_ext/models.py`                           | `GithubInstallation`, `RepoProjectMap`, `WorkItemGithubLink`, `StateTransitionConfig` (defined here, wired P2), `WebhookDelivery`.                                      |
| `github_ext/migrations/0001_initial.py`          | Own migration. **Never** touch `db/migrations/`. No columns on core models.                                                                                             |
| `github_ext/urls.py`                             | `path("github/webhook/", GithubWebhookView.as_view())` → mounted at `api/` (tp2) ⇒ `POST /api/github/webhook/`.                                                         |
| `github_ext/webhook/verify.py`                   | `verify_signature(secret, raw_body, header) -> bool` using `hmac.new(...).hexdigest()` + `hmac.compare_digest`.                                                         |
| `github_ext/webhook/views.py`                    | `GithubWebhookView`: read raw body → verify **pre-parse** → dedup on `X-GitHub-Delivery` → 202 fast-ack → enqueue dispatch.                                             |
| `github_ext/bgtasks/{__init__,dispatch}.py`      | `@shared_task(name="plane.github_ext.bgtasks.dispatch.route_event", bind=True, max_retries=2)`; enqueue via `transaction.on_commit` (mirror `ai_ext/signals.py:40-51`). |
| `github_ext/services/{installation,repo_map}.py` | Handle `installation`/`installation_repositories` events → upsert `GithubInstallation`; auto-seed `RepoProjectMap` (repo → inferred project).                           |
| `github_ext/signals.py`                          | (Empty/placeholder in P0; ready-hook target.)                                                                                                                           |
| `github_ext/tests/test_webhook.py`               | HMAC + idempotency + fast-ack tests.                                                                                                                                    |
| **core (tp1)** `settings/common.py`              | append `"plane.github_ext",` to `INSTALLED_APPS` after `"plane.workload",`.                                                                                             |
| **core (tp2)** `urls.py`                         | append `path("api/", include("plane.github_ext.urls")),` before `api/v1/ plane.api.urls`.                                                                               |

---

## Concrete steps

1. **Scaffold app** via `plane-scaffold-feature` (or by hand mirroring `ai_ext/`): `__init__.py`,
   `apps.py` (label `github_ext`, guarded `ready()` import of `signals`).
2. **Wire tp1 + tp2** (the ONLY two core edits). Fence each with a
   `# The1Studio fork (github_ext)` comment.
3. **Models + migration:**
   - `GithubInstallation(installation_id unique, account_login, workspace FK, config JSON, created/updated)`.
   - `RepoProjectMap(installation FK, repo_full_name, project FK, unique(installation, repo_full_name))`.
   - `WorkItemGithubLink(issue FK, project FK, type ∈ {branch,pr,commit,issue}, external_id, url, metadata JSON, unique(issue, type, external_id))` — defined now, written in P1.
   - `StateTransitionConfig(scope ∈ {global,project}, project FK null, rules JSON)` — defined now, used in P2.
   - `WebhookDelivery(delivery_id unique, event_type, received_at, status, headers JSON)` — idempotency ledger; **do not store token/secret bytes**.
   - `makemigrations github_ext` → commit `0001_initial.py`.
4. **HMAC verify (`verify.py`):** compute `sha256=` hexdigest over the **raw request body bytes**
   with `GITHUB_WEBHOOK_SECRET` (from `Integration.webhook_secret` for `provider="github"`, or
   env); compare to `X-Hub-Signature-256` header with `hmac.compare_digest`. Return bool.
5. **Webhook view (`views.py`):** `BaseAPIView` subclass, `AllowAny` (auth IS the HMAC).
   Order is load-bearing: **(a) read `request.body` raw → (b) `verify_signature` → 401 on fail
   → (c) parse JSON → (d) `WebhookDelivery.get_or_create(delivery_id=X-GitHub-Delivery)` → if
   existing, return 200 (idempotent no-op) → (e) `transaction.on_commit(lambda:
route_event.apply_async(...))` → (f) return `202 Accepted`.** Never `json.loads` before step (b).
6. **Dispatch task (`dispatch.py`):** load the `WebhookDelivery` + payload, switch on
   `event_type`; for `installation*` → call `services/installation.py` + `repo_map.py`
   auto-seed; for `push`/`pull_request`/`issues`/`issue_comment` → log + no-op in P0 (P1/P2
   fill these). Mark `WebhookDelivery.status`.
7. **Auto-seed `RepoProjectMap`:** on `installation`/`installation_repositories`, for each repo
   infer the project (by name match / config) and upsert a `RepoProjectMap` row; leave editable
   via the P4 API/MCP surface. Unmatched repo → row with `project=null` (surfaced, never
   silently mapped).
8. **GitHub App registration (operator doc, not code):** document the App manifest — least-priv
   perms (Contents r, PRs r/w, Issues r/w, Metadata r, Checks r), events (`push`,
   `pull_request`, `issues`, `issue_comment`, `installation`, `installation_repositories`),
   webhook URL `https://<host>/api/github/webhook/`, secret → `plane-deploy` env
   `GITHUB_WEBHOOK_SECRET`. Private key + App ID → `plane-deploy` env. **No secrets committed.**

---

## Risk assessment (P0-local)

| Risk                                              | L   | I   | Score  | Mitigation                                                                                                 |
| ------------------------------------------------- | --- | --- | ------ | ---------------------------------------------------------------------------------------------------------- |
| HMAC verify runs AFTER parse (forgery window)     | 3   | 5   | **15** | Enforce order in `views.py`; test feeds a bad-signature body and asserts 401 + `json.loads` never reached. |
| Non-constant-time compare (timing attack)         | 2   | 4   | 8      | `hmac.compare_digest` only; grep-gate forbids `==` on signatures.                                          |
| Redelivery double-processing                      | 4   | 2   | 8      | `WebhookDelivery unique(delivery_id)` + `get_or_create` short-circuit.                                     |
| Slow handler → GitHub 10s timeout + retries storm | 3   | 3   | 9      | Fast-ack 202 before any heavy work; all logic in Celery via `on_commit`.                                   |
| Repo→project auto-seed guesses wrong project      | 3   | 3   | 9      | Infer conservatively; `project=null` when unsure; never default-map. Editable in P4.                       |
| Migration not checked in / drift                  | 2   | 3   | 6      | `makemigrations --check` gate.                                                                             |

---

## Test list (`pytest plane/github_ext/tests/test_webhook.py`)

- Valid signature → 202; `WebhookDelivery` row created; dispatch enqueued (mock `apply_async`).
- **Bad signature → 401**, and assert the JSON body was NOT parsed (patch `json.loads`, assert not called).
- Missing `X-Hub-Signature-256` → 401.
- Duplicate `X-GitHub-Delivery` → second POST returns 200 idempotent, no second enqueue.
- `installation` event → `GithubInstallation` upserted + `RepoProjectMap` seeded (matched repo)
  and `project=null` for an unmatched repo.
- Constant-time: signature compare goes through `hmac.compare_digest` (assert via patch/spy).

## Gates (all must pass)

- `plane-isolation-audit` → only `settings/common.py` + `urls.py` changed in core.
- `docker exec api sh -c 'cd /code && python manage.py makemigrations --check --dry-run'`
- `docker exec api sh -c 'cd /code && python manage.py check'`
- `docker exec api sh -c 'cd /code && pytest plane/github_ext'`

## Rollback

Drop the two touch-point lines + `git rm -r github_ext/`; migration is app-local (never
applied to core tables) so `migrate github_ext zero` cleanly removes the 5 tables. No core
schema touched → zero cascade.
