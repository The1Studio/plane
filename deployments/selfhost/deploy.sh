#!/usr/bin/env bash
#
# Self-hosted build + deploy for the master fork of Plane.
# Invoked by .github/workflows/deploy-master.yml  (production) and
#            .github/workflows/deploy-staging.yml (staging) on the server runner.
#
# One script, two environments. Everything environment-specific arrives as an
# env var, and every default reproduces production byte-for-byte:
#
#   RUN_DIR           /opt/plane-fork-app       dir holding plane.env + the compose file
#   IMAGE_TAG         companymain               tag for the 6 built images -> APP_RELEASE
#   HEALTH_HTTP_PORT  80                        host port the health checks probe
#   COMPOSE_PROJECT   $(basename $RUN_DIR)      explicit `docker compose -p` value
#   LOCAL_DB          1                         run the bundled postgres container
#   LOCAL_STORAGE     1                         run the bundled minio container
#   PG_IMAGE          pgvector/pgvector:pg15    image for the bundled postgres
#
# LOCAL_DB / LOCAL_STORAGE exist because production does NOT use the bundled
# services: its DATABASE_URL points at Neon (pg17) and its uploads go to
# Cloudflare R2. Both containers nevertheless kept running unattended, holding
# stale pre-migration copies of real data and ~220MB of RAM, because the
# upstream compose file defines them with no profile gate. Setting either to 0
# gates that service out (see build_override below).
#
# Preconditions on the server:
#   - Docker + docker compose v2 available to the runner user.
#   - $RUN_DIR exists and contains plane.env (secrets, IP, ports) — NOT in git.
#   - Runs FROM the checked-out repo root ($GITHUB_WORKSPACE / cwd).
#
set -euo pipefail

export DOCKER_BUILDKIT=1

NS="makeplane"                       # image namespace (matches deployments/cli/community/docker-compose.yml)
TAG="${IMAGE_TAG:-companymain}"      # tag referenced by APP_RELEASE in plane.env
RUN_DIR="${RUN_DIR:-/opt/plane-fork-app}"
SHA="$(git rev-parse --short HEAD)"
WORKSPACE="$(pwd)"

# Host port the post-deploy health checks probe. MUST match LISTEN_HTTP_PORT in
# this environment's plane.env. Defaulting to 80 reproduces production exactly.
#
# This is not cosmetic. Until 2026-08-26 the checks below hardcoded
# `http://localhost/`, so a SECOND stack on another port would have probed
# *production* and reported a green deploy for a stack that never started —
# a check that cannot go red when the thing it guards is broken.
HEALTH_HTTP_PORT="${HEALTH_HTTP_PORT:-80}"
HEALTH_BASE="http://localhost:${HEALTH_HTTP_PORT}"

# Explicit compose project name. The default is the run-dir basename, which is
# precisely what docker compose derives implicitly — so for production this
# resolves to `plane-fork-app` and ADOPTS the existing containers and named
# volumes (plane-fork-app_pgdata, ...). Do not change this default: any other
# value orphans production's database volume and brings the stack up empty.
COMPOSE_PROJECT="${COMPOSE_PROJECT:-$(basename "$RUN_DIR")}"

# Bundled backing services. Defaults are 1/1 — i.e. today's behaviour on every
# existing install — so an environment that wants them gone opts out explicitly
# rather than being opted out by a default it never read.
LOCAL_DB="${LOCAL_DB:-1}"
LOCAL_STORAGE="${LOCAL_STORAGE:-1}"

# Image for the bundled postgres. The default keeps pg15, which is what
# production's (now unused) pgdata volume was initialised with — a pg17 binary
# refuses to start on a pg15 data directory, so changing this default would
# break any install that still runs the bundled DB. Staging asks for pg17 to
# match production's Neon server version (17.11).
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:pg15}"

echo "==> Repo:      $WORKSPACE"
echo "==> Commit:    $SHA"
echo "==> Image tag: $NS/plane-*:$TAG (+ :git-$SHA)"
echo "==> Run dir:   $RUN_DIR"
echo "==> Project:   $COMPOSE_PROJECT"
echo "==> Health:    $HEALTH_BASE"
echo "==> Local DB:  $LOCAL_DB ($PG_IMAGE)"
echo "==> Local S3:  $LOCAL_STORAGE"

# ---------------------------------------------------------------------------
# 1) Build the 6 images from source. Context matches deployments/cli/community/build.yml:
#    web/space/admin/live -> repo root (pnpm+turbo monorepo); api -> apps/api; proxy -> apps/proxy.
# ---------------------------------------------------------------------------
build() {  # <image-name> <dockerfile> <context>
  local name="$1" dockerfile="$2" context="$3"
  echo "==> build $NS/$name"
  docker build \
    -f "$dockerfile" \
    -t "$NS/$name:$TAG" \
    -t "$NS/$name:git-$SHA" \
    "$context"
}

build plane-frontend apps/web/Dockerfile.web       .
build plane-space     apps/space/Dockerfile.space   .
build plane-admin     apps/admin/Dockerfile.admin   .
build plane-live      apps/live/Dockerfile.live     .
build plane-backend   apps/api/Dockerfile.api       apps/api
build plane-proxy     apps/proxy/Dockerfile.ce      apps/proxy

# ---------------------------------------------------------------------------
# 2) Sync compose into the run dir (preserve plane.env), apply pgvector fix.
#    master's ai_ext module needs the pgvector extension; the upstream
#    compose ships postgres:15.7-alpine (no pgvector), so patch it here.
# ---------------------------------------------------------------------------
if [ ! -f "$RUN_DIR/plane.env" ]; then
  echo "ERROR: $RUN_DIR/plane.env not found. Create it once (secrets/IP/ports) before enabling CI."
  exit 1
fi

cp deployments/cli/community/docker-compose.yml "$RUN_DIR/docker-compose.yaml"
sed -i "s|image: postgres:15.7-alpine|image: ${PG_IMAGE}|" "$RUN_DIR/docker-compose.yaml"

# ---------------------------------------------------------------------------
# 2b) Gate out bundled services this environment does not use.
#
# Written as a fork-owned OVERRIDE file rather than an edit to the upstream
# compose. deployments/cli/community/docker-compose.yml is pristine upstream
# (its last commits are all upstream PRs), and editing it would be a fork edit
# outside the seven documented touch-points in docs/FORK.md — a rebase-conflict
# generator for no benefit, since compose overrides do the job natively.
#
# plane-minio is trivially gateable: nothing depends_on it.
# plane-db is NOT: api, worker, beat-worker and migrator all depend_on it, and
# the compose spec errors when a non-profiled service depends on a profiled
# one. So the override must also rewrite those four depends_on lists, which is
# what `!override` is for (requires Compose >= 2.24; server runs v5.3.1).
# ---------------------------------------------------------------------------
OVERRIDE="$RUN_DIR/docker-compose.override.yaml"
rm -f "$OVERRIDE"          # never leave a stale override behind when flags flip back

if [ "$LOCAL_DB" = "0" ] || [ "$LOCAL_STORAGE" = "0" ]; then
  {
    echo "# Generated by deployments/selfhost/deploy.sh — do not edit by hand."
    echo "# Regenerated on every deploy from LOCAL_DB / LOCAL_STORAGE."
    echo "services:"
    if [ "$LOCAL_DB" = "0" ]; then
      cat <<'YAML'
  plane-db:
    profiles: ["local-db"]
  api:
    depends_on: !override [plane-redis, plane-mq]
  worker:
    depends_on: !override [api, plane-redis, plane-mq]
  beat-worker:
    depends_on: !override [api, plane-redis, plane-mq]
  migrator:
    depends_on: !override [plane-redis]
YAML
    fi
    if [ "$LOCAL_STORAGE" = "0" ]; then
      cat <<'YAML'
  plane-minio:
    profiles: ["local-storage"]
YAML
    fi
  } > "$OVERRIDE"
  echo "==> wrote $OVERRIDE (LOCAL_DB=$LOCAL_DB LOCAL_STORAGE=$LOCAL_STORAGE)"
fi

# Compose file list, used by every docker compose call below.
COMPOSE_FILES=(-f docker-compose.yaml)
[ -f "$OVERRIDE" ] && COMPOSE_FILES+=(-f docker-compose.override.yaml)

# Keep APP_RELEASE in plane.env aligned with the tag we just built.
if grep -q '^APP_RELEASE=' "$RUN_DIR/plane.env"; then
  sed -i "s|^APP_RELEASE=.*|APP_RELEASE=$TAG|" "$RUN_DIR/plane.env"
else
  echo "APP_RELEASE=$TAG" >> "$RUN_DIR/plane.env"
fi

# ---------------------------------------------------------------------------
# 3) Deploy. --pull never because images are local (tags not on Docker Hub).
# ---------------------------------------------------------------------------
cd "$RUN_DIR"
docker compose -p "$COMPOSE_PROJECT" "${COMPOSE_FILES[@]}" --env-file=plane.env up -d --pull never --remove-orphans

# ---------------------------------------------------------------------------
# 3b) Enforce the gate on ALREADY-RUNNING containers.
#
# `up -d` does NOT stop a service that a profile gated out. Profiles govern what
# STARTS, and --remove-orphans only removes services absent from the compose
# file entirely — plane-db is still defined there, merely profiled. So without
# this step the deploy prints "Local DB: 0", writes the override, and leaves the
# container running: the log claims the gate took effect while nothing changed.
# Observed on production 2026-08-26, run 32949970398.
#
# Containers are addressed by compose's own project+service labels rather than
# by name, so this is not coupled to the container-naming scheme. `docker rm`
# removes the container only — named volumes (plane-fork-app_pgdata,
# plane-fork-app_uploads) are untouched and survive for a later re-enable via
# `--profile local-db` / `--profile local-storage`.
# ---------------------------------------------------------------------------
gate_off_service() {  # <compose-service-name>
  local svc="$1" ids
  ids="$(docker ps -aq \
          --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
          --filter "label=com.docker.compose.service=$svc" || true)"
  if [ -n "$ids" ]; then
    echo "==> gating off $svc (removing $(echo "$ids" | wc -l) container(s); volumes kept)"
    # shellcheck disable=SC2086
    docker rm -f $ids >/dev/null
  else
    echo "==> $svc already absent"
  fi
}

if [ "$LOCAL_DB" = "0" ]; then
  gate_off_service plane-db
fi
if [ "$LOCAL_STORAGE" = "0" ]; then
  gate_off_service plane-minio
fi

# ---------------------------------------------------------------------------
# 4) Health check: wait for migrations + API. Fail the job on timeout.
# ---------------------------------------------------------------------------
# Poll BOTH endpoints together. Previously only `api` was retried and `web` got a
# single probe immediately after that loop exited — which passed only by accident:
# when `api` was also recreated the loop spent ~26s cycling, and that incidental
# delay was what gave `web` time to start. On a deploy that recreates `web` but not
# `api` (compose leaves unchanged services running) the loop broke on its first
# pass and the lone `web` probe fired 16ms after the container started, returning a
# transient 502 and failing an otherwise healthy deploy. Observed 2026-08-22, run
# 32561842827.
echo "==> Waiting for API and web to become healthy at $HEALTH_BASE ..."
api=""
web=""
for _ in $(seq 1 60); do          # up to ~5 min
  api="$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_BASE/api/instances/" || true)"
  web="$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_BASE/" || true)"
  [ "$api" = "200" ] && [ "$web" = "200" ] && break
  sleep 5
done

echo "==> health: base=$HEALTH_BASE web=$web api=$api"

if [ "$web" != "200" ] || [ "$api" != "200" ]; then
  echo "ERROR: health check failed. Recent logs:"
  # `web` is included deliberately: it is the service most likely to be the one
  # failing here, and omitting it meant a web-side failure dumped only api logs.
  docker compose -p "$COMPOSE_PROJECT" "${COMPOSE_FILES[@]}" --env-file=plane.env logs --tail=60 migrator api web || true
  exit 1
fi

# ---------------------------------------------------------------------------
# 5) Bounded cache prune (keep some for fast rebuilds; server disk is tight).
# ---------------------------------------------------------------------------
docker builder prune -f --keep-storage=20GB >/dev/null 2>&1 || true

echo "==> Deploy OK  (commit $SHA, tag $TAG, project $COMPOSE_PROJECT)"
