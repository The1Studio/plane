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
#   KEEP_GIT_TAGS     5                         newest :git-* tags kept per repo
#
# KEEP_GIT_TAGS bounds step 6's prune of the :git-<sha> tags every deploy adds.
# Nothing removed them before, so they accumulated one full set per deploy —
# ~100 stale tags on sv-2, whose root disk reached 86%. The newest N are kept so
# a rollback to a recent build still needs no rebuild; raise it on a host with
# room, lower it on a host without.
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

# Newest :git-* tags kept per repository by the step-6 prune. Guarded because a
# non-numeric value makes every `-le` comparison in there fail, and the prune is
# best-effort — so a typo would silently prune nothing, forever, while the log
# said the step ran.
KEEP_GIT_TAGS="${KEEP_GIT_TAGS:-5}"
case "$KEEP_GIT_TAGS" in
  ''|*[!0-9]*)
    echo "WARN: KEEP_GIT_TAGS='$KEEP_GIT_TAGS' is not a number; using 5"
    KEEP_GIT_TAGS=5
    ;;
esac

echo "==> Repo:      $WORKSPACE"
echo "==> Commit:    $SHA"
echo "==> Image tag: $NS/plane-*:$TAG (+ :git-$SHA)"
echo "==> Keep tags: $KEEP_GIT_TAGS newest :git-* per repo"
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
# 2c) Give plane-redis cache semantics. UNCONDITIONAL — unlike the gates above,
#     this does not depend on LOCAL_DB / LOCAL_STORAGE, so the override is now
#     always written.
#
#     Upstream ships plane-redis with no `command:`, which means Valkey defaults
#     to maxmemory=0 + noeviction. That is wrong for a pure cache: once memory
#     fills, it returns ERRORS ON WRITES instead of evicting cold keys — the
#     cache breaks the application rather than shedding load. Harmless while the
#     keyspace was 3 keys; live from the moment plane/workload_cache started
#     writing ~320 KB response entries.
#
#     allkeys-lru, NOT volatile-lru: volatile-* can only evict keys carrying an
#     expiry, and workload_cache entries are written with none (allkeys-lru is
#     their sole reclamation path). Under volatile-lru they would be entirely
#     unevictable and the instance would fill and start refusing writes — the
#     exact failure this removes.
#
#     save "" disables RDB. This holds nothing that is not recomputable, so the
#     periodic background fork + disk write buys nothing.
#
#     Rationale and measurements: plans/260826-redis-cache-workload-perf/phase-1.md
OVERRIDE="$RUN_DIR/docker-compose.override.yaml"
rm -f "$OVERRIDE"          # never leave a stale override behind when flags flip back

{
  echo "# Generated by deployments/selfhost/deploy.sh — do not edit by hand."
  echo "# Regenerated on every deploy from LOCAL_DB / LOCAL_STORAGE."
  echo "services:"
  cat <<'YAML'
  plane-redis:
    command: >
      valkey-server
      --maxmemory 1gb
      --maxmemory-policy allkeys-lru
      --save ""
YAML
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
echo "==> wrote $OVERRIDE (LOCAL_DB=$LOCAL_DB LOCAL_STORAGE=$LOCAL_STORAGE, redis cache config always on)"

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

# ---------------------------------------------------------------------------
# 6) Prune old :git-* image tags. Bounded, best-effort, never fails the deploy.
#
# Every deploy tags all 6 images twice: :$TAG (the tag APP_RELEASE points at) and
# :git-$SHA (the immutable record of that build). Nothing ever removed the
# :git-* half, so each deploy added a permanent set — ~100 stale tags had built
# up on sv-2, whose root disk reached 86%. Step 5 does not help here: these are
# TAGGED images, not builder cache.
#
# Staging (:staging) and production (:companymain) deploy on the SAME host and
# share these repositories, so the prune must never take out something the other
# environment still points at. Four rules, cheapest first:
#
#   1. Only :git-* tags are candidates. Every other tag — :$TAG, :staging,
#      :companymain, :latest — is out of scope by construction.
#   2. An image referenced by ANY container, running OR stopped, in ANY compose
#      project is skipped. Stopped ones count: `docker compose up -d` recreates
#      from the image already on disk, and `docker start` fails on a pruned one.
#   3. An image that a NON-:git- tag of the SAME repo resolves to is skipped, so
#      the :staging / :companymain images survive even while no container
#      references them (between deploys, or after `docker compose down`).
#   4. The newest $KEEP_GIT_TAGS tags per repo are skipped, so rolling back to a
#      recent build needs no rebuild.
#
# `docker rmi` WITHOUT -f is the backstop under all four: if any rule above
# missed a case, the daemon refuses rather than yanking an image out from under a
# live container. A refusal is logged and never retried with -f.
#
# The whole step is best-effort — a prune that cannot run is a disk problem to
# solve later, never a reason to fail a deploy that just went green.
# ---------------------------------------------------------------------------

# Image IDs referenced by any container, running or stopped, any project.
#
# Resolved via `docker inspect` on the container rather than `docker ps --format
# {{.Image}}`: the latter reports the reference the container was STARTED with (a
# tag, a short id, or a full sha), while `.Image` from the container's own config
# is always the canonical sha256. It also keeps resolving after the tag that
# started the container is gone — the exact situation this prune creates.
container_image_ids() {
  local cids cid
  cids="$(docker ps -aq 2>/dev/null || true)"
  while IFS= read -r cid; do
    [ -n "$cid" ] || continue
    docker inspect --format '{{.Image}}' "$cid" 2>/dev/null || true
  done <<< "$cids"
  return 0
}

prune_git_tags() {
  local repo keep="${KEEP_GIT_TAGS:-5}" rows in_use protected git_rows
  local idx id ref removed=0

  # ONE snapshot of the image list, shared by all 6 repos. A `docker images`
  # re-read inside the loop would observe a list this function is itself
  # mutating as it untags images.
  rows="$(docker images --no-trunc --format '{{.ID}}|{{.Repository}}:{{.Tag}}|{{.CreatedAt}}' 2>/dev/null || true)"

  # Membership sets are flattened to space-delimited strings so a lookup is a
  # single `case` glob — no associative arrays, nothing past bash-3 builtins.
  in_use=" $(container_image_ids | sort -u | tr '\n' ' ')"

  for repo in plane-frontend plane-space plane-admin plane-live plane-backend plane-proxy; do
    # Rule 3, scoped to THIS repo by the "repo:" prefix — plane-backend's
    # :staging must not protect a plane-frontend tag that shares an image ID.
    protected="$(printf '%s\n' "$rows" | awk -F'|' -v p="$NS/$repo:" '
      index($2, p) == 1 && substr($2, length(p) + 1, 4) != "git-" { print $1 }
    ' | sort -u | tr '\n' ' ')"

    # Candidate tags, newest image first. CreatedAt is ISO-8601 UTC, so a
    # reverse lexical sort over the "created|id|ref" record is a correct
    # newest-first sort; the id/ref tail only breaks ties.
    git_rows="$(printf '%s\n' "$rows" | awk -F'|' -v p="$NS/$repo:" '
      index($2, p) == 1 && substr($2, length(p) + 1, 4) == "git-" { print $3"|"$1"|"$2 }
    ' | sort -r)"

    idx=0
    while IFS='|' read -r _ id ref; do
      [ -n "$ref" ] || continue
      # Plain assignment, not `((idx++))`: the arithmetic form returns 1 when
      # the result is 0, which under `set -e` aborts on the first iteration.
      idx=$((idx + 1))
      if [ "$idx" -le "$keep" ]; then
        continue                                   # rule 4
      fi
      case " $in_use " in
        *" $id "*) continue ;;                     # rule 2
      esac
      case " $protected " in
        *" $id "*) continue ;;                     # rule 3
      esac
      if docker rmi "$ref" >/dev/null 2>&1; then
        removed=$((removed + 1))
        echo "==>   removed $ref"
      else
        echo "==>   kept    $ref (in use)"
      fi
    done <<< "$git_rows"
  done

  # Dangling images only. Untagging above is what orphans them, and this is what
  # reclaims the layers — `-a` would also take TAGGED images, which on this host
  # means images the other environment still deploys from.
  docker image prune -f >/dev/null 2>&1 || true

  echo "==> pruned $removed old git-* tags"
}

prune_git_tags || true

echo "==> Deploy OK  (commit $SHA, tag $TAG, project $COMPOSE_PROJECT)"
