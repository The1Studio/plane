# Self-hosted deployment — `server`

Both Plane environments for the The1Studio fork run as Docker Compose stacks on one machine,
deployed by GitHub Actions through a self-hosted runner. This is the operational runbook; the
branch model and rebase policy live in [`docs/FORK.md`](../../docs/FORK.md), which is the
governance SSOT.

## The two environments

|                   | Production                                  | Staging                                        |
| ----------------- | ------------------------------------------- | ---------------------------------------------- |
| Branch            | `master`                                    | `staging`                                      |
| Workflow          | `.github/workflows/deploy-master.yml`       | `.github/workflows/deploy-staging.yml`         |
| Run dir           | `/opt/plane-fork-app`                       | `/opt/plane-staging-app`                       |
| Compose project   | `plane-fork-app`                            | `plane-staging-app`                            |
| Image tag         | `companymain`                               | `staging`                                      |
| HTTP / HTTPS port | `80` / `8443`                               | `81` / `8543`                                  |
| Domain            | `plane.the1studio.org`                      | `plane-staging.the1studio.org`                 |
| Uploads           | Cloudflare R2 via worker proxy              | bundled MinIO container                        |
| Database          | **Neon** (managed, pg17.11)                 | bundled `pgvector/pgvector:pg17`, starts empty |
| Bundled db/minio  | gated OFF (`LOCAL_DB=0`, `LOCAL_STORAGE=0`) | both ON                                        |
| Concurrency group | `deploy-master`                             | `deploy-staging`                               |

The two share **nothing**: separate run directory, compose project (so separate container names
_and_ separate named volumes), image tags, host ports, `plane.env` with independently generated
secrets, and object storage. Both are exposed through the same Cloudflare tunnel, which is
token-managed — its ingress rules live in the Zero Trust dashboard, not in a file on the host.

## The environment seam

`deploy.sh` is one script driving both stacks. Everything environment-specific arrives as an
environment variable set by the calling workflow, and **every default reproduces production
byte-for-byte**:

| Variable           | Default                  | Meaning                                                 |
| ------------------ | ------------------------ | ------------------------------------------------------- |
| `RUN_DIR`          | `/opt/plane-fork-app`    | Directory holding `plane.env` + the synced compose file |
| `IMAGE_TAG`        | `companymain`            | Tag for the 6 built images, mirrored into `APP_RELEASE` |
| `HEALTH_HTTP_PORT` | `80`                     | Host port the post-deploy health checks probe           |
| `COMPOSE_PROJECT`  | `$(basename "$RUN_DIR")` | Explicit `docker compose -p` value                      |

`notify-discord.sh` adds two more:

| Variable    | Default                        | Meaning                                 |
| ----------- | ------------------------------ | --------------------------------------- |
| `ENV_LABEL` | `production`                   | Embed title and the `Environment` field |
| `SITE_URL`  | `https://plane.the1studio.org` | The `Site` field value                  |

Both workflows set all six explicitly even where the default would do, so neither can drift from
the other through a default nobody re-reads.

> **`COMPOSE_PROJECT` is the dangerous one.** Its default resolves to `plane-fork-app` for
> production, which is exactly the name docker compose already derived implicitly — so the
> existing containers and volumes (`plane-fork-app_pgdata`, …) are adopted. Any other value
> orphans production's database volume and brings the stack up against an empty database. Verify
> before changing it:
>
> ```bash
> cd /opt/plane-fork-app && docker compose -p plane-fork-app -f docker-compose.yaml \
>   --env-file=plane.env ps --format '{{.Name}}' | sort
> docker ps --format '{{.Names}}' | grep ^plane-fork-app | sort
> ```
>
> The two listings must be identical.

## Deploying

**Production** — merge to `master`. That is a production deployment; there is no separate release
step. `workflow_dispatch` re-runs the current `master`.

**Staging** — push to `staging`, or deploy any ref on demand:

```bash
gh workflow run deploy-staging.yml -f ref=<branch-tag-or-sha>
```

That `ref` input is what makes staging useful for validating an upstream rebase candidate without
force-pushing `staging` first — see `docs/FORK.md` § "Rebase-on-tags workflow" step 7.

Both workflows skip `**/*.md` and `docs/**` via `paths-ignore`, so a docs-only commit does not
trigger a 90-minute image build.

### Runner serialization is expected, not a fault

There is exactly **one** self-hosted runner (`sv-0`, registered at the The1Studio org level). A
staging build and a production build therefore queue behind each other even though their
concurrency groups are separate. This is accepted: worst case is 90 minutes, and the local Docker
layer cache is shared between the two, so a staging build right after a production build of a
nearby commit is much faster than a cold one. If it ever becomes a real problem, the fix is a
second runner, not a workflow change.

## First-time staging provisioning

`/opt/plane-staging-app/plane.env` and the Cloudflare public hostname are **not** in git and must
be created by hand once. The full checklist, with per-step verification, is
[`plans/260826-plane-staging-deploy/phase-4.md`](../../plans/260826-plane-staging-deploy/phase-4.md).
Start from [`plane.env.staging.example`](plane.env.staging.example) and generate every secret
fresh — a shared `SECRET_KEY` means a session token minted in staging validates in production.

## Cloning production data into staging

Staging starts empty on purpose: a from-zero migration is the thing an upstream rebase most often
breaks, and an empty database is what exercises it. When you specifically need to rehearse a
migration against real row volumes:

```bash
bash deployments/selfhost/clone-prod-db-to-staging.sh --yes-wipe-staging
```

**This drops and recreates the staging database.** Without the flag the script prints what it
would do and exits non-zero, having run no docker command. Production is opened only through
`pg_dump` — there is no write path to it anywhere in the script. After restoring, it runs the
staging migrator so the real rows meet the current checkout's migrations.

Note that cloning discards the from-zero migration state, so re-verify that separately afterwards
if you still need it (`docker compose -p plane-staging-app exec -T api python manage.py showmigrations`).

## When a deploy fails

The health check reports the base URL it probed:

```
==> health: base=http://localhost:81 web=502 api=200
```

If that base is not the port you expected, the workflow's `HEALTH_HTTP_PORT` and the stack's
`LISTEN_HTTP_PORT` disagree — the deploy may be fine and the check wrong, or vice versa.

First move on any failure:

```bash
docker compose -p <project> -f /opt/<dir>/docker-compose.yaml \
  --env-file=/opt/<dir>/plane.env logs --tail=60 migrator api web
```

The deploy script already dumps exactly this on a health-check failure, so it should be in the
workflow log.

Common causes, in the order they actually occur: a migration failed (read `migrator`), the build
succeeded but an env var is missing (read `api`), or the proxy came up before `web` was ready
(transient — the health loop polls both together for 5 minutes precisely to absorb this).

## Resource budget

Measured on `server`, 2026-08-26, with production running alone:

|                | Value                                          |
| -------------- | ---------------------------------------------- |
| Memory         | 31G total, 8G used, 23G available              |
| Disk           | 469G total, 256G free (43% used)               |
| Docker images  | 105 / 30.68GB                                  |
| Docker volumes | 336 / 24.19GB                                  |
| Build cache    | 21.29GB (pruned to a 20GB ceiling each deploy) |

Staging adds roughly 12 containers and ~15GB of images. Disk is not a concern. **Memory is the
one to watch**: if available memory drops below about 6G, stop the staging stack between test
cycles rather than leaving it running —

```bash
docker compose -p plane-staging-app -f /opt/plane-staging-app/docker-compose.yaml \
  --env-file=/opt/plane-staging-app/plane.env stop
```

Every staging service is pinned to one replica and `GUNICORN_WORKERS=1` for the same reason.

## Files here

| File                          | Purpose                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------ |
| `deploy.sh`                   | Build the 6 images, sync compose into the run dir, `up -d`, health-gate, prune |
| `notify-discord.sh`           | Post the deploy result to Discord; never fails the job                         |
| `plane.env.staging.example`   | Template for `/opt/plane-staging-app/plane.env`                                |
| `clone-prod-db-to-staging.sh` | On-demand production → staging database clone                                  |

## See also

- [`docs/FORK.md`](../../docs/FORK.md) — branch model, promotion path, rebase policy (governance SSOT)
- [`plans/260826-plane-staging-deploy/`](../../plans/260826-plane-staging-deploy/) — the plan that built the staging environment
