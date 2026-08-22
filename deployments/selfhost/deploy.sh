#!/usr/bin/env bash
#
# Self-hosted build + deploy for the company-main fork of Plane.
# Invoked by .github/workflows/deploy-company-main.yml on the server runner.
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

echo "==> Repo:      $WORKSPACE"
echo "==> Commit:    $SHA"
echo "==> Image tag: $NS/plane-*:$TAG (+ :git-$SHA)"
echo "==> Run dir:   $RUN_DIR"

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
#    company-main's ai_ext module needs the pgvector extension; the upstream
#    compose ships postgres:15.7-alpine (no pgvector), so patch it here.
# ---------------------------------------------------------------------------
if [ ! -f "$RUN_DIR/plane.env" ]; then
  echo "ERROR: $RUN_DIR/plane.env not found. Create it once (secrets/IP/ports) before enabling CI."
  exit 1
fi

cp deployments/cli/community/docker-compose.yml "$RUN_DIR/docker-compose.yaml"
sed -i 's|image: postgres:15.7-alpine|image: pgvector/pgvector:pg15|' "$RUN_DIR/docker-compose.yaml"

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
docker compose -f docker-compose.yaml --env-file=plane.env up -d --pull never --remove-orphans

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
echo "==> Waiting for API and web to become healthy..."
api=""
web=""
for _ in $(seq 1 60); do          # up to ~5 min
  api="$(curl -s -o /dev/null -w '%{http_code}' http://localhost/api/instances/ || true)"
  web="$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ || true)"
  [ "$api" = "200" ] && [ "$web" = "200" ] && break
  sleep 5
done

echo "==> health: web=$web api=$api"

if [ "$web" != "200" ] || [ "$api" != "200" ]; then
  echo "ERROR: health check failed. Recent logs:"
  # `web` is included deliberately: it is the service most likely to be the one
  # failing here, and omitting it meant a web-side failure dumped only api logs.
  docker compose -f docker-compose.yaml --env-file=plane.env logs --tail=60 migrator api web || true
  exit 1
fi

# ---------------------------------------------------------------------------
# 5) Bounded cache prune (keep some for fast rebuilds; server disk is tight).
# ---------------------------------------------------------------------------
docker builder prune -f --keep-storage=20GB >/dev/null 2>&1 || true

echo "==> Deploy OK  (commit $SHA, tag $TAG)"
