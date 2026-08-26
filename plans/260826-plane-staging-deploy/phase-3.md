# Phase 3 — Staging env template, DB clone script, runbook

**Plan:** [`plan.md`](plan.md) · **Depends on:** [Phase 1](phase-1.md) · **Parallel-safe with:** [Phase 2](phase-2.md)
**Effort:** S (~1 day)

## Goal

Ship the three artefacts an operator needs to stand up and live with the staging stack: a
committed env template, a guarded production→staging database clone script, and a runbook that
documents both environments in one place.

## Files owned

- `deployments/selfhost/plane.env.staging.example` **(new)**
- `deployments/selfhost/clone-prod-db-to-staging.sh` **(new)**
- `deployments/selfhost/README.md` **(new)**

Do not touch `deploy.sh` or `notify-discord.sh` (Phase 1) or any workflow (Phase 2).

## Inherited contract from Phase 1

`deploy.sh` reads `RUN_DIR`, `IMAGE_TAG`, `HEALTH_HTTP_PORT`, `COMPOSE_PROJECT`;
`notify-discord.sh` additionally reads `ENV_LABEL` and `SITE_URL`. The README documents these as
the environment seam; do not invent alternative names.

## Changes

### 1. `plane.env.staging.example`

A committed **template**, never a real env file. Every secret is an obvious placeholder that would
fail loudly if used verbatim. It is read by a human in Phase 4, who copies it to
`/opt/plane-staging-app/plane.env` and fills it in — that path is outside the repo and is never
committed, exactly as production's is.

Base it on the live production `plane.env` key set, which is (read from `server`, 2026-08-26):

```
APP_DOMAIN APP_RELEASE WEB_REPLICAS SPACE_REPLICAS ADMIN_REPLICAS API_REPLICAS
WORKER_REPLICAS BEAT_WORKER_REPLICAS LIVE_REPLICAS LISTEN_HTTP_PORT LISTEN_HTTPS_PORT
WEB_URL DEBUG CORS_ALLOWED_ORIGINS API_BASE_URL PGHOST PGDATABASE POSTGRES_USER
POSTGRES_PASSWORD POSTGRES_DB POSTGRES_PORT PGDATA DATABASE_URL REDIS_HOST REDIS_PORT
REDIS_URL RABBITMQ_HOST RABBITMQ_PORT RABBITMQ_USER RABBITMQ_PASSWORD RABBITMQ_VHOST
AMQP_URL CERT_ACME_CA TRUSTED_PROXIES SITE_ADDRESS CERT_EMAIL CERT_ACME_DNS SECRET_KEY
USE_MINIO AWS_REGION AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY FILE_SIZE_LIMIT
GUNICORN_WORKERS MINIO_ENDPOINT_SSL API_KEY_RATE_LIMIT AUTHENTICATION_RATE_LIMIT
LIVE_SERVER_SECRET_KEY WEBHOOK_ALLOWED_IPS WEBHOOK_ALLOWED_HOSTS
```

The values that **must** differ from production:

| Key                                                                              | Staging value                          | Why                                                                                                                                                   |
| -------------------------------------------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `APP_DOMAIN`                                                                     | `staging-plane.the1studio.org`         | The new tunnel hostname                                                                                                                               |
| `WEB_URL`                                                                        | `https://staging-plane.the1studio.org` | Auth callbacks and absolute links                                                                                                                     |
| `CORS_ALLOWED_ORIGINS`                                                           | `https://staging-plane.the1studio.org` | Must not list the production origin                                                                                                                   |
| `APP_RELEASE`                                                                    | `staging`                              | `deploy.sh` rewrites this anyway; seed it correctly so a manual `docker compose up` before the first CI deploy does not pull `stable` from Docker Hub |
| `LISTEN_HTTP_PORT`                                                               | `8081`                                 | Verified free on `server`                                                                                                                             |
| `LISTEN_HTTPS_PORT`                                                              | `8543`                                 | Verified free on `server`                                                                                                                             |
| `SITE_ADDRESS`                                                                   | `:80`                                  | Container-internal; Cloudflare terminates TLS, so Caddy must not attempt ACME. Same as production.                                                    |
| `USE_MINIO`                                                                      | `1`                                    | Local MinIO, per the plan's resolved decision 5                                                                                                       |
| `MINIO_ENDPOINT_SSL`                                                             | `0`                                    | MinIO is plain HTTP inside the compose network                                                                                                        |
| `AWS_S3_ENDPOINT_URL`                                                            | _omit entirely_                        | See the warning below                                                                                                                                 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`                                    | fresh random values                    | These double as the MinIO root credentials (`x-minio-env` in the compose maps them), so they must be set — just not to production's R2 keys           |
| `AWS_S3_BUCKET_NAME`                                                             | `uploads`                              | The compose default; MinIO creates it locally                                                                                                         |
| `SECRET_KEY`, `LIVE_SERVER_SECRET_KEY`, `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD` | freshly generated                      | A shared secret between environments means a staging session token is valid in production                                                             |
| `DEBUG`                                                                          | `0`                                    | Staging mirrors production. Turning it on changes Django's error handling and would mask the very failures staging exists to catch.                   |
| `*_REPLICAS`, `GUNICORN_WORKERS`                                                 | `1`                                    | Memory budget — see the plan's risk table                                                                                                             |

> **The R2 guard is an absence, not a flag.** `USE_MINIO=1` is what _selects_ MinIO, but what
> actually makes it impossible for staging to write into production's `plane-uploads` bucket is
> that the staging env carries **no R2 credentials and no `AWS_S3_ENDPOINT_URL` at all**. A flag
> can be flipped by a future edit; a credential that was never present cannot be. Put a comment
> to that effect directly above the storage block so nobody "helpfully" copies the production
> values across.

Head the file with a comment block stating: this is a template, the real file lives at
`/opt/plane-staging-app/plane.env` on `server`, it is not in git, and every secret must be
regenerated rather than copied from production. Include the generation one-liner
(`openssl rand -hex 32` or `python3 -c 'import secrets;print(secrets.token_hex(32))'`).

### 2. `clone-prod-db-to-staging.sh`

The on-demand half of resolved decision 4: staging starts empty, and this script exists for the
case where a migration needs rehearsing against real row volumes.

**It is destructive to staging by design, so it is built to be un-misfireable:**

- **One-directional by construction.** Production is opened only through `pg_dump` inside the
  production container; there is no `psql` invocation anywhere that targets the production project.
  The direction cannot be inverted by swapping an argument, because the production side has no
  write path in the script at all.
- **Refuses without `--yes-wipe-staging`.** No prompt, no default-yes, no `-f`. Print what it would
  do and exit non-zero when the flag is absent.
- **Asserts the restore target.** Read the target compose project into a variable and abort unless
  it is literally `plane-staging-app`. Do not accept it as an argument — a hardcoded literal that
  the script checks against is the guard; a parameter is the hole.
- **Aborts if the production stack is not running**, so a typo cannot silently produce an empty
  dump that then wipes staging and restores nothing.
- Runs the staging `migrator` afterwards, so the restored schema is brought up to the staging
  checkout's migration state — the whole point of the rehearsal.

Shape:

```bash
docker compose -p plane-fork-app     … exec -T plane-db pg_dump  …   # read production
  │
  └─► docker compose -p plane-staging-app … exec -T plane-db psql …  # wipe + restore staging
```

Stream the dump rather than writing a multi-GB temp file, and stop the staging `api` / `worker` /
`beat-worker` services before the restore so nothing writes mid-transaction. Bring them back up at
the end, including on failure — a `trap` is appropriate here.

Print, at the top of every run, exactly which project is the source and which is the target. The
operator reading the output should be able to tell the direction without reading the script.

### 3. `deployments/selfhost/README.md`

The runbook. There is currently no document describing the self-hosted deployment at all — this is
the first. Cover:

- **The two environments**, as a table: branch, workflow, run dir, compose project, image tag,
  host ports, domain, storage backend. Copy the concrete values from the plan's _Concrete staging
  values_ table rather than re-deriving them.
- **The environment seam** — the six variables from the Phase 1 contract, what each defaults to,
  and why every default reproduces production.
- **First-time staging provisioning**, pointing at Phase 4's checklist rather than duplicating it.
- **How to deploy an arbitrary ref to staging** — the `workflow_dispatch` `ref` input from Phase 2,
  with the `gh workflow run` invocation spelled out.
- **How to clone production data**, with the exact flag and the warning that it wipes staging.
- **Runner serialization** — one `sv-0` runner exists, so a staging build and a production build
  queue behind each other. This is expected, not a fault. Say so here so nobody debugs it twice.
- **What to check when a deploy fails** — the health-check output names the probed base URL after
  Phase 1, and `docker compose -p <project> logs --tail=60 migrator api web` is the first move.
- **Memory and disk budget** — the measured baseline (31G RAM with ~8G used by production alone;
  256G free disk against a 30.68GB image footprint) and the rule of thumb that staging should be
  stopped between test cycles if available memory drops below ~6G.

## Success criteria

1. `bash -n deployments/selfhost/clone-prod-db-to-staging.sh` exits 0; `shellcheck` is clean.
2. Running the clone script with no flags prints its intent and exits **non-zero**, having executed
   no `docker` command. Verify with `set -x` or by confirming `docker ps` output is unchanged.
3. `grep -iE 'r2|plane-uploads|workers\.dev' deployments/selfhost/plane.env.staging.example`
   returns **nothing** except inside the explanatory comment.
4. Every key present in production's `plane.env` is present in the template, except
   `AWS_S3_ENDPOINT_URL`, whose absence IS the R2 guard. Check with:
   `comm -23 <(ssh server 'grep -oE "^[A-Z0-9_]+=" /opt/plane-fork-app/plane.env | tr -d "="' | sort -u) <(grep -oE "^#? *[A-Z0-9_]+=" deployments/selfhost/plane.env.staging.example | tr -d "#= " | sort -u)`
   — output must be exactly `AWS_S3_ENDPOINT_URL` and nothing else.

   **The character class must be `[A-Z0-9_]`, not `[A-Z_]`.** A `[A-Z_]+` pattern cannot match a
   key containing a digit, so it silently skips `AWS_S3_ENDPOINT_URL` and `AWS_S3_BUCKET_NAME` —
   the two keys this check most needs to see. It then reports a clean parity for a template
   missing both, which is a green that proves nothing. Observed while implementing this phase:
   the flawed regex found 50 production keys, the correct one finds 52.

5. No real secret is committed: `git diff --cached` before commit shows only placeholder values,
   and the repo's existing secret-scanning gate passes.

## Out of scope

- Creating the real `/opt/plane-staging-app/plane.env` — Phase 4 (it never enters git).
- Running the clone script for real — Phase 5 verifies it refuses without the flag; an actual
  clone is an on-demand operator action, not a plan step.
- Backup or retention policy for either database.
