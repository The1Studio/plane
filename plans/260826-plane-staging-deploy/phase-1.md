# Phase 1 — Parameterize the shared deploy scripts

**Plan:** [`plan.md`](plan.md) · **Depends on:** nothing · **Blocks:** Phases 2 and 3
**Effort:** S (~0.5 day) · **Runs serial** — this phase declares the shape both later lanes consume.

## Goal

Make `deployments/selfhost/deploy.sh` and `deployments/selfhost/notify-discord.sh` capable of
driving _either_ environment, while every default reproduces today's production behaviour exactly.
After this phase, production still deploys byte-for-byte as it does now; staging simply becomes
expressible.

## Files owned

- `deployments/selfhost/deploy.sh`
- `deployments/selfhost/notify-discord.sh`

Touch nothing else. Workflow files belong to Phase 2, env templates to Phase 3.

## Why this phase exists separately

`deploy.sh` already reads `RUN_DIR` and `IMAGE_TAG` from the environment, so the multi-environment
seam is half-built. Two things are still hardcoded to production and would break a second stack:

1. **The health check probes `http://localhost/`** — port 80, production's proxy. A staging stack
   on port 81 would have its health check silently probe _production_ and pass, reporting a green
   deploy for a staging stack that never came up. This is the failure this phase primarily exists
   to prevent: the check would not go red when the thing it guards is broken.
2. **The compose project name is implicit**, derived by docker compose from the run directory's
   basename. That happens to be correct for both environments, but leaving it implicit means a
   future change to `RUN_DIR` silently renames the project and orphans its volumes. Make it
   explicit and defaulted.

## Changes

### 1. `deploy.sh` — health-check port

Currently (`deploy.sh`, the health-check block):

```bash
api="$(curl -s -o /dev/null -w '%{http_code}' http://localhost/api/instances/ || true)"
web="$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ || true)"
```

Introduce near the other variable definitions at the top:

```bash
HEALTH_HTTP_PORT="${HEALTH_HTTP_PORT:-80}"
HEALTH_BASE="http://localhost:${HEALTH_HTTP_PORT}"
```

and probe `"$HEALTH_BASE/api/instances/"` and `"$HEALTH_BASE/"`.

Keep the existing loop shape exactly as it is — both endpoints polled **together** inside one
retry loop. That structure is load-bearing and carries a comment explaining why (a previous version
probed `web` once after the `api` loop exited and failed healthy deploys with a transient 502 on
2026-08-22, run 32561842827). Do not restructure it while you are in the file.

Echo the resolved base URL in the existing `==> Waiting for API and web…` line so a failed run
shows which stack was probed.

### 2. `deploy.sh` — explicit compose project

Add near the top:

```bash
COMPOSE_PROJECT="${COMPOSE_PROJECT:-$(basename "$RUN_DIR")}"
```

and pass `-p "$COMPOSE_PROJECT"` to **every** `docker compose` invocation in the file — there are
two: the `up -d` call and the `logs` call inside the health-failure branch. Missing the second one
would make a failed deploy dump the wrong stack's logs.

Add the resolved project name to the `==>` banner block at the top of the script alongside
`Repo` / `Commit` / `Image tag` / `Run dir`.

> **Read this before you change the compose invocation.** `$(basename /opt/plane-fork-app)` is
> `plane-fork-app`, which is _exactly_ the project name docker compose already derives implicitly
> for production. Passing it explicitly is therefore a no-op for the running stack: the same
> containers and the same named volumes (`plane-fork-app_pgdata`, `plane-fork-app_uploads`, …) are
> adopted. If you hardcode any other default, production's database volume is orphaned and the
> stack comes up against an empty database. Verify this before merging — see Verification below.

### 3. `notify-discord.sh` — environment label and site URL

The embed currently hardcodes production in two places: the title strings
(`✅ Plane deploy thành công` / `❌ Plane deploy thất bại`) and the `Site` field value
(`https://plane.the1studio.org`).

Add two variables with production-preserving defaults:

```bash
ENV_LABEL="${ENV_LABEL:-production}"
SITE_URL="${SITE_URL:-https://plane.the1studio.org}"
```

Export them into the Python heredoc's environment the same way the existing `GH_*` variables reach
it, and build the title as `Plane <ENV_LABEL> deploy thành công` / `… thất bại`, keeping the
existing ✅/❌ prefix and colour logic untouched. Add the label as an `Environment` field in the
embed too — the thread may carry both environments, so the reader needs to tell them apart at a
glance without parsing the title.

Keep the script's fail-open contract intact: it must still `exit 0` on any webhook error, because
it runs under `if: always()` and must never turn a successful deploy red.

## Success criteria

Verifiable by command, not by reading the diff.

1. `bash -n deployments/selfhost/deploy.sh` and `bash -n deployments/selfhost/notify-discord.sh`
   both exit 0.
2. `shellcheck` reports no new errors versus the pre-change files (warnings that already existed
   may stay).
3. With no new variables set, the resolved values are identical to today's:
   `RUN_DIR=/opt/plane-fork-app`, `IMAGE_TAG=companymain`, `HEALTH_HTTP_PORT=80`,
   `COMPOSE_PROJECT=plane-fork-app`.
4. **The volume-adoption check, run on `server` before merge:**

   ```bash
   ssh server 'cd /opt/plane-fork-app && \
     docker compose -p plane-fork-app -f docker-compose.yaml --env-file=plane.env ps --format "{{.Name}}" | sort'
   ```

   Its output must match the currently-running container list
   (`ssh server 'docker ps --format "{{.Names}}" | grep ^plane-fork-app | sort'`) exactly. A
   mismatch means the explicit project name does not resolve to the existing stack — stop and fix
   before merging.

5. `ssh server 'docker volume ls --format "{{.Name}}" | grep ^plane-fork-app_ | sort'` returns the
   same list before and after the change.

## Out of scope

- Any workflow file. Phase 2 owns those, including passing the new variables.
- Creating the staging `plane.env`. Phase 3 owns the template; Phase 4 owns the real file.
- Changing the build steps, the pgvector `sed`, or the `--keep-storage` prune value.
