# Plane staging branch + staging deployment on `server`

Stand up a second, fully isolated Plane stack on the same self-hosted machine that already runs
production, driven by a new `staging` branch through the same GitHub Actions self-hosted runner.

**Created:** 2026-08-26
**Mode:** default (research → plan → validate)
**Plane:** [PLANE-187](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/2601560e-91c7-4c12-bf0a-db2ba8d79cac) — Todo, 28h estimated
**Cook handoff:** `/t1k:cook plans/260826-plane-staging-deploy/`

---

## Verified starting state

Every fact below was read from the repo or from the live `server` host over SSH on 2026-08-26.
Nothing here is recalled or assumed.

| Fact                            | Value                                                                                                                                                                                            | Source                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| Production branch               | `master`                                                                                                                                                                                         | `.github/workflows/deploy-master.yml:6`                                                    |
| Deploy trigger                  | push to `master` (paths-ignore `**/*.md`, `docs/**`) + `workflow_dispatch`                                                                                                                       | `deploy-master.yml:4-13`                                                                   |
| Runner                          | `[self-hosted, sv-0]`, org-level runner registered to `github.com/The1Studio`                                                                                                                    | `deploy-master.yml:19`; `server:/home/dietpi/actions-runner/.runner` (`agentName: sv-0`)   |
| Runner count                    | **one** — a single `Runner.Listener` process for `sv-0`                                                                                                                                          | `server: ps aux \| grep Runner.Listener`                                                   |
| Deploy script                   | `deployments/selfhost/deploy.sh`, env-driven via `RUN_DIR` + `IMAGE_TAG`                                                                                                                         | `deploy-master.yml:26-30`                                                                  |
| Prod run dir                    | `/opt/plane-fork-app` (contains `docker-compose.yaml`, `plane.env`, `r2-proxy/`)                                                                                                                 | `server: ls /opt/plane-fork-app`                                                           |
| Prod compose project            | `plane-fork-app` (implicit, from run-dir basename)                                                                                                                                               | docker compose default behaviour                                                           |
| Prod image tag                  | `companymain`, applied to 6 locally-built images                                                                                                                                                 | `deploy.sh:16`                                                                             |
| Prod host ports                 | HTTP `80`, HTTPS `8443`                                                                                                                                                                          | `server:/opt/plane-fork-app/plane.env`                                                     |
| Prod domain                     | `plane.the1studio.org`                                                                                                                                                                           | `plane.env` `APP_DOMAIN` / `WEB_URL`                                                       |
| Public exposure                 | `cloudflared tunnel run --token …` (**token-managed** — ingress lives in the Cloudflare dashboard, not on disk; there is no `/etc/cloudflared/config.yml`)                                       | `server: ps aux \| grep cloudflared`; `ls /etc/cloudflared` returns nothing                |
| Prod object storage             | Cloudflare R2 via worker proxy, `USE_MINIO=0`, bucket `plane-uploads`                                                                                                                            | `plane.env`                                                                                |
| Prod database                   | **Neon** (managed Postgres, server_version **17.11**, 126 tables, extensions `plpgsql,vector`) — NOT the bundled container                                                                       | `docker exec plane-fork-app-api-1` reading `DATABASE_URL` + a Django `show server_version` |
| Prod bundled db/minio           | **Running but unused** — `plane-db` (pg15, 185MB stale volume, 126 stale tables) and `plane-minio` (43 stale files); ~220MB RAM between them. Upstream compose defines both with no profile gate | `docker ps`, `docker stats`, `docker run --rm -v ...`                                      |
| DB resolution order             | `settings/common.py:200` — `if DATABASE_URL: ... else: POSTGRES_*`. An `if/else`, so with `DATABASE_URL` set the `PG*` branch never runs; that branch reads `POSTGRES_HOST`, not `PGHOST`        | `apps/api/plane/settings/common.py:200-211`                                                |
| Host disk                       | 469G total, **256G free** (43% used)                                                                                                                                                             | `server: df -h /`                                                                          |
| Host memory                     | 31G total, 8G used, 23G available                                                                                                                                                                | `server: free -g`                                                                          |
| Docker footprint                | 105 images / 30.68GB, 336 volumes / 24.19GB, 21.29GB build cache                                                                                                                                 | `server: docker system df`                                                                 |
| `plane-minio` service           | present in the community compose **unconditionally**, no profile gate, **no host port published**                                                                                                | `deployments/cli/community/docker-compose.yml:207-217`                                     |
| Proxy host ports                | `${LISTEN_HTTP_PORT:-80}` / `${LISTEN_HTTPS_PORT:-443}`, `mode: host`                                                                                                                            | same file, `:228-236`                                                                      |
| CI gate                         | `master-ci.yml`, push + PR on `master` only, deliberately **no** `paths:` filter                                                                                                                 | `master-ci.yml:11-17`                                                                      |
| Other PR gates                  | `pull-request-build-lint-api.yml`, `…-web-apps.yml`, `copyright-check.yml`, `codeql.yml` — all filter `branches: ["master"]`                                                                     | each file's `on:` block                                                                    |
| FORK.md already assumes staging | Rebase recipe step 7 reads _"Staging: migrate + smoke"_ against a stack that **does not exist**                                                                                                  | `docs/FORK.md:68-70`                                                                       |

**Free host ports** (probed live with `ss -ltn "sport = :$p"`): `81`, `8100`, `8180`, `9080`,
`8444`, `8543` are free. `8080`, `8090`, `9443` are **taken**.

### Correction — production's backing services (found 2026-08-26, mid-implementation)

An earlier revision of this plan stated production's database was its own
`pgvector/pgvector:pg15` container. **That was wrong.** Production's `DATABASE_URL` points at
**Neon** (pg17.11); the bundled `plane-db` container holds only a stale pre-Neon copy and nothing
reads it. The same is true of `plane-minio` against Cloudflare R2.

Three things followed from the correction:

1. `clone-prod-db-to-staging.sh` originally dumped the production compose project's `plane-db`
   container — i.e. the stale copy. It would have produced a plausible, complete-looking 126-table
   dump of outdated data, restored it, run the migrator, and printed "clone complete" while never
   touching the real database. Now it reads `DATABASE_URL` from production's `plane.env` and dumps
   Neon, and refuses outright if that URL ever points back at `plane-db`.
2. Staging was pinned to pg15 against a pg17.11 production, which defeats the migration-rehearsal
   argument that justified the clone feature at all. Staging now pins `PG_IMAGE=pgvector/pgvector:pg17`.
3. The two unused production containers are now gated off (`LOCAL_DB=0`, `LOCAL_STORAGE=0`).

### Prior-art gate

Searched across `.github/workflows/`, `deployments/`, `docs/`, and the repo root. Findings:

- **`deployments/selfhost/deploy.sh` already parameterizes `RUN_DIR` and `IMAGE_TAG`** — the
  multi-environment seam is half-built. It does **not** parameterize the health-check port or the
  compose project name, which is exactly what a second stack needs. Extend it; do not write a
  second script.
- **`deployments/selfhost/notify-discord.sh` already exists** and is env-driven, except the site
  URL and the embed title, which are hardcoded to production. Extend it.
- `feature-deployment.yml` deploys per-branch previews to **Kubernetes via Helm and Tailscale**
  (upstream's `feature.plane.tools` infrastructure). It is unrelated to the self-hosted server and
  is not a usable base — none of its secrets (`FEATURE_PREVIEW_KUBE_CONFIG`,
  `TAILSCALE_OAUTH_*`) are configured for The1Studio.
- Zero staging-stack definition anywhere: `grep -rn "plane-staging\|staging" --include='*.yml'
--include='*.sh' .github/ deployments/` returns no deployment target. `/opt/plane-staging-app`
  does not exist on `server` (`ls /opt` shows `plane-fork`, `plane-fork-app`, `plane-selfhost` —
  the first and third are stale checkouts, not running stacks).
- `docker-compose.yml` needs **no fork edit** for staging: MinIO is already a service, and every
  port, credential, and storage switch is driven from `plane.env`.

---

## Resolved decisions

These were decided with the user before this plan was written. They are facts, not options.

| #   | Decision                       | Resolution                                                                                                                                                                                                                                                                                                                                          |
| --- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Branch model                   | **Integration branch.** Features merge into `staging`; `staging` merges up into `master`.                                                                                                                                                                                                                                                           |
| 2   | Post-rebase policy             | **Reset staging to master, re-merge open features.** Staging's merge history is disposable by design.                                                                                                                                                                                                                                               |
| 3   | Exposure                       | **New Cloudflare tunnel hostname** — `plane-staging.the1studio.org` → `http://localhost:81`.                                                                                                                                                                                                                                                        |
| 4   | Staging data                   | **Fresh empty DB**, plus a documented on-demand script to clone production when a migration rehearsal needs real rows.                                                                                                                                                                                                                              |
| 5   | Object storage                 | **Local MinIO inside the staging stack** (`USE_MINIO=1`). Fully isolated from prod's R2 bucket.                                                                                                                                                                                                                                                     |
| 6   | Discord notifications          | **Same thread as production** (`1524317964160204800`). The `ENV_LABEL` / `Environment` embed field distinguishes them.                                                                                                                                                                                                                              |
| 7   | Access control                 | **None — matching production.** Verified 2026-08-26: `https://plane.the1studio.org/` returns 200 to an anonymous request with no CF-Access headers, so production has no Access policy and Plane's own login is the only gate. Staging matches. (Originally taken as "same policy as production" on the false premise that production _was_ gated.) |
| 8   | Branch protection on `staging` | **None.** The branch is disposable and gets force-pushed after every upstream rebase; protection would fight that. PRs into `staging` still run all four CI gates regardless.                                                                                                                                                                       |

### Concern on record — decision 1 vs. the rebase workflow

The integration-branch model collides with this fork's monthly `git rebase <upstream-tag>` on
`master`: the rebase rewrites the very history `staging` was branched from, so `staging` diverges
from `master` by the entire rebased range and every promotion afterwards becomes a conflict fight.

The user chose it anyway, which is their call, and decision 2 is what makes it survivable — after
each rebase, `staging` is hard-reset to `master` and open features are re-merged, so the
divergence is discarded rather than reconciled. **That reset is the load-bearing step**; skipping
it once puts `staging` permanently out of sync. Phase 6 writes it into `docs/FORK.md` as a
mandatory post-rebase step, not a suggestion.

---

## Target architecture

```
                    ┌──────────────────── server (DietPi, 31G RAM, 256G free) ────────────────────┐
                    │                                                                              │
 GitHub             │   runner sv-0 (single, org-level, serializes all jobs)                       │
 ─────────          │        │                                                                     │
 master ───push───► │        ├─► deploy-master.yml                                                 │
                    │        │     RUN_DIR=/opt/plane-fork-app   IMAGE_TAG=companymain             │
                    │        │     HEALTH_HTTP_PORT=80                                             │
                    │        │        └─► compose project `plane-fork-app`                         │
                    │        │              :80 / :8443 · R2 uploads · Neon pg17.11              │
                    │        │                                                                     │
 staging ──push───► │        └─► deploy-staging.yml            ◄── NEW                             │
                    │              RUN_DIR=/opt/plane-staging-app  IMAGE_TAG=staging               │
                    │              HEALTH_HTTP_PORT=81                                           │
                    │                 └─► compose project `plane-staging-app`                      │
                    │                       :81 / :8543 · MinIO · bundled pg17                   │
                    │                                                                              │
                    │   cloudflared (token-managed tunnel)                                         │
                    │     plane.the1studio.org          ──► localhost:80                           │
                    │     plane-staging.the1studio.org  ──► localhost:81   ◄── NEW (dashboard)   │
                    └──────────────────────────────────────────────────────────────────────────────┘
```

**Isolation is total across both stacks:** separate run directory, separate compose project name
(so separate container names _and_ separate named volumes — `plane-staging-app_pgdata` never
touches `plane-fork-app_pgdata`), separate image tags, separate host ports, separate `plane.env`
with independently-generated secrets, and separate object storage.

### Concrete staging values

| Setting          | Production             | Staging                                                                                                                              |
| ---------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Branch           | `master`               | `staging`                                                                                                                            |
| Run dir          | `/opt/plane-fork-app`  | `/opt/plane-staging-app`                                                                                                             |
| Compose project  | `plane-fork-app`       | `plane-staging-app`                                                                                                                  |
| Image tag        | `companymain`          | `staging`                                                                                                                            |
| HTTP port        | `80`                   | `81`                                                                                                                                 |
| HTTPS port       | `8443`                 | `8543`                                                                                                                               |
| Domain           | `plane.the1studio.org` | `plane-staging.the1studio.org`                                                                                                       |
| `USE_MINIO`      | `0` (R2)               | `1` (local MinIO)                                                                                                                    |
| `DEBUG`          | `0`                    | `0` (staging mirrors prod; do **not** enable — it changes Django error handling and would mask the failures staging exists to catch) |
| Health-check URL | `http://localhost/`    | `http://localhost:81/`                                                                                                               |

---

## Phases

| Phase | Title                                                                | Depends on | Parallel-safe with                       | Effort                                         |
| ----- | -------------------------------------------------------------------- | ---------- | ---------------------------------------- | ---------------------------------------------- |
| 1     | [Parameterize the shared deploy scripts](phase-1.md)                 | —          | — (serial: declares the shared contract) | S (~0.5d)                                      |
| 2     | [Staging deploy workflow + CI gate widening](phase-2.md)             | 1          | 3                                        | S (~0.5d)                                      |
| 3     | [Staging env template, DB clone script, runbook](phase-3.md)         | 1          | 2                                        | S (~1d)                                        |
| 4     | [Server + Cloudflare + GitHub provisioning](phase-4.md)              | 2, 3       | —                                        | S (~0.5d, operator-driven)                     |
| 5     | [First deploy and smoke verification](phase-5.md)                    | 4          | —                                        | S (~0.5d)                                      |
| 6     | [Documentation — FORK.md branch model and rebase policy](phase-6.md) | 5          | —                                        | S (~0.5d)                                      |
|       | **Total**                                                            |            |                                          | **~3.5 days**, critical path 1 → 2 → 4 → 5 → 6 |

Phase 1 is deliberately serial and first. It changes the two scripts **both** environments call,
so it is the shared shape that must be fixed before anything forks — per
`rules/contract-first-integration.md`, a declaration consumed by two lanes is hoisted into the
serial phase ahead of the fan-out.

### File ownership (zero-overlap invariant)

No file appears under two phases.

| Phase | Files owned                                                                                                                                                                                                                                                                                                    |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | `deployments/selfhost/deploy.sh`, `deployments/selfhost/notify-discord.sh`                                                                                                                                                                                                                                     |
| 2     | `.github/workflows/deploy-staging.yml` (new), `.github/workflows/deploy-master.yml`, `.github/workflows/master-ci.yml`, `.github/workflows/pull-request-build-lint-api.yml`, `.github/workflows/pull-request-build-lint-web-apps.yml`, `.github/workflows/copyright-check.yml`, `.github/workflows/codeql.yml` |
| 3     | `deployments/selfhost/plane.env.staging.example` (new), `deployments/selfhost/clone-prod-db-to-staging.sh` (new), `deployments/selfhost/README.md` (new)                                                                                                                                                       |
| 4     | none in git — operator actions on `server`, in the Cloudflare dashboard, and on GitHub                                                                                                                                                                                                                         |
| 5     | none in git — verification only                                                                                                                                                                                                                                                                                |
| 6     | `docs/FORK.md`, `.claude/rules/plane-fork-discipline.md`                                                                                                                                                                                                                                                       |

### The integration contract (pinned — Phases 2 and 3 both depend on it)

Phase 1 establishes this and Phases 2–3 consume it verbatim. Every name and default below is
exact; do not paraphrase them at a call site.

`deployments/selfhost/deploy.sh` reads these environment variables:

| Variable           | Default                  | Meaning                                                        |
| ------------------ | ------------------------ | -------------------------------------------------------------- |
| `RUN_DIR`          | `/opt/plane-fork-app`    | Directory holding `plane.env` + the synced compose file        |
| `IMAGE_TAG`        | `companymain`            | Tag applied to the 6 built images, mirrored into `APP_RELEASE` |
| `HEALTH_HTTP_PORT` | `80`                     | Host port the post-deploy health checks probe                  |
| `COMPOSE_PROJECT`  | `$(basename "$RUN_DIR")` | Explicit `docker compose -p` value                             |

`deployments/selfhost/notify-discord.sh` gains two variables on top of its existing set:

| Variable    | Default                        | Meaning                                                               |
| ----------- | ------------------------------ | --------------------------------------------------------------------- |
| `ENV_LABEL` | `production`                   | Appears in the embed title, e.g. `✅ Plane staging deploy thành công` |
| `SITE_URL`  | `https://plane.the1studio.org` | The `Site` field value in the embed                                   |

**Every default reproduces today's production behaviour byte-for-byte.** `COMPOSE_PROJECT`
defaulting to the run-dir basename resolves to `plane-fork-app`, which is precisely the implicit
project name production already uses — so production's existing containers and named volumes are
adopted, not orphaned. This is the single most dangerous line in the plan and Phase 1 verifies it
explicitly before the change is allowed to merge.

---

## Risk Assessment

| Risk                                                                                                                                        | Likelihood (1-5) | Impact (1-5) | Score  | Mitigation                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------ | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `COMPOSE_PROJECT` change orphans production's named volumes (`plane-fork-app_pgdata` → a new empty project) — production data appears wiped | 2                | 5            | **10** | Default is `$(basename "$RUN_DIR")` = `plane-fork-app`, identical to today's implicit name. Phase 1 gates on `docker compose -p plane-fork-app -f … config --volumes` and `docker volume ls` matching the running stack **before** merge, and Phase 5 re-verifies after the first staging deploy.          |
| Staging and production compete for the single `sv-0` runner; a staging build delays a production hotfix                                     | 4                | 2            | 8      | Separate concurrency groups (`deploy-master`, `deploy-staging`) so neither cancels the other. Runner serialization is accepted, not fixed — a staging build is ≤90 min worst case and shares the local layer cache. Documented in the Phase 3 runbook; a second runner is the escalation if it ever bites. |
| Memory exhaustion — a second full stack (12 containers) alongside production plus build peaks                                               | 2                | 4            | 8      | 23G currently available against a measured 8G production footprint. Staging pins every `*_REPLICAS=1` and `GUNICORN_WORKERS=1`. Phase 5 records `free -g` and `docker stats` post-deploy as the baseline; if headroom drops below ~6G, stop the staging stack between test cycles.                         |
| Staging writes into production's R2 bucket (`plane-uploads`) and destroys real uploads                                                      | 2                | 5            | **10** | `USE_MINIO=1` and **no** `AWS_S3_*` R2 credentials in the staging `plane.env` at all — the absent credential is the real guard, not the flag. Phase 5 asserts an upload lands in the staging MinIO volume and that `plane-uploads` object count is unchanged.                                              |
| The DB clone script runs against the wrong direction and overwrites production                                                              | 1                | 5            | 5      | Script is one-directional by construction (prod is opened read-only via `pg_dump`, never `psql`), hard-codes the staging project as the only restore target, refuses unless `--yes-wipe-staging` is passed, and aborts if the target project name does not literally equal `plane-staging-app`.            |
| Cloudflare ingress cannot be scripted (token-managed tunnel) so the hostname silently never gets added                                      | 3                | 3            | 9      | Phase 4 makes it an explicit operator checklist item with a `curl` verification, and Phase 5's smoke test fails loudly if `plane-staging.the1studio.org` does not resolve to the staging stack.                                                                                                            |
| Widening `master-ci.yml` to `staging` creates a required-check deadlock                                                                     | 2                | 3            | 6      | `master-ci.yml` carries no `paths:` filter and must not gain one (`ci-cd-trigger-design` §3). Phase 2 only adds branch names to existing `on:` blocks. If `staging` is given branch protection, the same checks are already running on it.                                                                 |
| Disk pressure from a second set of images + a shared build cache                                                                            | 2                | 3            | 6      | 256G free against a 30.68GB image footprint; staging adds ~15GB. `docker builder prune --keep-storage=20GB` already runs per deploy and is shared. Phase 5 records `docker system df` as a baseline.                                                                                                       |
| Post-rebase `staging` reset is forgotten, leaving staging permanently diverged                                                              | 3                | 3            | 9      | Phase 6 writes the reset into `docs/FORK.md` as a numbered, mandatory step **inside** the rebase recipe (not an appendix), and into `.claude/rules/plane-fork-discipline.md` so it auto-loads every session.                                                                                               |

No risk scores ≥ 15. The two scoring 10 are both data-loss shaped and each has a verification gate
in Phase 5 rather than a mitigation-by-intent.

---

## Success criteria

The whole plan is done when all of the following hold, each verified by running the command, not
by inspection:

1. `git push origin staging` triggers `deploy-staging.yml`, which completes green on `sv-0`.
2. `https://plane-staging.the1studio.org/` returns 200 and serves the staging build.
3. `https://plane.the1studio.org/` still returns 200, and `docker volume ls | grep plane-fork-app`
   lists the same volumes with the same names as before Phase 1.
4. The two stacks share no container, no volume, no port, and no credential —
   `docker compose -p plane-fork-app ps` and `docker compose -p plane-staging-app ps` have
   disjoint output.
5. A file uploaded in staging lands in the staging MinIO volume, and production's `plane-uploads`
   R2 bucket object count is unchanged.
6. A PR targeting `staging` runs `master CI`, the api lint, the web lint, and the copyright check.
7. `docs/FORK.md` describes the `staging` branch, the promotion path, and the mandatory
   post-rebase reset.

---

## Out of scope

Stated so nobody expects them:

- A second GitHub Actions runner. Serialization on `sv-0` is accepted for now.
- Branch protection rules on `staging` — decided against (decision 8).
- Automatic promotion `staging` → `master`. Promotion stays a human-opened PR.
- Any change to `feature-deployment.yml` (upstream's unrelated Kubernetes preview path).
- Blue/green or zero-downtime deploys for either environment. Both remain
  `docker compose up -d` with a health gate.
