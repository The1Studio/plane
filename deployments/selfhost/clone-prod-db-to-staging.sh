#!/usr/bin/env bash
#
# Clone the PRODUCTION Plane database into the STAGING stack, on demand.
#
# Staging normally starts empty — that is deliberate, because a from-zero
# migration is the thing an upstream rebase most often breaks. This script
# exists for the other case: rehearsing a migration against real row volumes
# before it runs on production.
#
#   Source: production's DATABASE_URL -> Neon (managed Postgres) — READ ONLY
#   Target: compose project `plane-staging-app` local pg17     — WIPED
#
# NOTE FOR ANYONE EDITING: the source is NOT the production compose project's
# `plane-db` container. Production's DATABASE_URL points at Neon; the bundled
# plane-db container held only a stale pre-migration copy and is now gated off
# entirely (LOCAL_DB=0). An earlier version of this script dumped that container
# and would have produced a plausible, complete-looking dump of outdated data
# while never touching the real database — a failure that reports success.
#
# Run it on the `server` host, from a checkout of this repo:
#
#   bash deployments/selfhost/clone-prod-db-to-staging.sh --yes-wipe-staging
#
# WITHOUT that flag it prints what it would do and exits non-zero. There is no
# prompt and no -f: the flag is the only way through.
#
# Safety properties, in case you are about to edit this file:
#
#   * One-directional BY CONSTRUCTION. Production is opened only through
#     `pg_dump` against a URL read from its plane.env. No psql or restore path
#     in this script targets that URL, so the direction cannot be inverted by
#     swapping an argument — you would have to add a write path that does not
#     exist.
#   * pg_dump runs INSIDE the staging plane-db container, which is pg17 and so
#     is >= Neon's 17.11 server. A pg15 client refuses to dump a pg17 server —
#     a second reason staging pins PG_IMAGE=pgvector/pgvector:pg17.
#   * The target is a hardcoded literal that is asserted, never a parameter.
#     A parameter is the hole; the assertion is the guard.
#   * It refuses unless production's DATABASE_URL is readable and external,
#     so a misconfiguration cannot produce an empty dump that wipes staging
#     and restores nothing.
#
set -euo pipefail

PROD_DIR="/opt/plane-fork-app"
STAGING_PROJECT="plane-staging-app"
STAGING_DIR="/opt/plane-staging-app"

# --- guard 1: the flag ------------------------------------------------------
CONFIRMED=0
for arg in "$@"; do
  [ "$arg" = "--yes-wipe-staging" ] && CONFIRMED=1
done

cat <<BANNER
=============================================================================
  Plane database clone
    FROM  Neon  (DATABASE_URL in $PROD_DIR/plane.env)  -- read only, pg_dump
    INTO  $STAGING_PROJECT  local postgres             -- DROPPED AND RECREATED
=============================================================================
BANNER

if [ "$CONFIRMED" -ne 1 ]; then
  echo "REFUSING: this DESTROYS the staging database."
  echo "Re-run with --yes-wipe-staging if that is what you want."
  echo "Nothing was executed."
  exit 2
fi

# --- guard 2: the target is the one this script is allowed to wipe ----------
# Belt and braces against a future edit that turns the literal into a variable
# fed from somewhere else.
if [ "$STAGING_PROJECT" != "plane-staging-app" ]; then
  echo "ABORT: refusing to wipe a project other than plane-staging-app (got '$STAGING_PROJECT')."
  exit 1
fi

# --- guard 3: production's real source URL ---------------------------------
if [ ! -r "$PROD_DIR/plane.env" ]; then
  echo "ABORT: cannot read $PROD_DIR/plane.env — no source URL."
  exit 1
fi
PROD_DB_URL="$(grep -E "^DATABASE_URL=" "$PROD_DIR/plane.env" | head -1 | cut -d= -f2-)"
if [ -z "$PROD_DB_URL" ]; then
  echo "ABORT: production plane.env has no DATABASE_URL."
  exit 1
fi
# Refuse to silently dump the bundled container. If DATABASE_URL ever points
# back at plane-db, this script's premise is wrong and it needs re-reading
# before it is re-run.
case "$PROD_DB_URL" in
  *@plane-db/*|*@plane-db:*)
    echo "ABORT: production DATABASE_URL points at the bundled plane-db container,"
    echo "       not an external database. This script assumes an external source."
    exit 1 ;;
esac

# --- guard 4: the staging database must be up ------------------------------
stag_db="$(docker compose -p "$STAGING_PROJECT" ps -q plane-db 2>/dev/null || true)"
if [ -z "$stag_db" ]; then
  echo "ABORT: staging database container not running under project '$STAGING_PROJECT'."
  echo "       Deploy staging first, then re-run this."
  exit 1
fi

# Host only — never print the URL, it carries the password.
echo "==> source host:    $(printf "%s" "$PROD_DB_URL" | sed -E "s#.*@([^/?]+).*#\\1#")"
echo "==> stage plane-db: $stag_db"

# --- quiesce staging writers, and always bring them back -------------------
STAGING_WRITERS="api worker beat-worker live"

restore_writers() {
  echo "==> restarting staging writers ($STAGING_WRITERS)"
  # shellcheck disable=SC2086
  docker compose -p "$STAGING_PROJECT" -f "$STAGING_DIR/docker-compose.yaml" \
    --env-file="$STAGING_DIR/plane.env" up -d $STAGING_WRITERS || true
}
trap restore_writers EXIT

echo "==> stopping staging writers so nothing writes mid-restore"
# shellcheck disable=SC2086
docker compose -p "$STAGING_PROJECT" -f "$STAGING_DIR/docker-compose.yaml" \
  --env-file="$STAGING_DIR/plane.env" stop $STAGING_WRITERS

# --- wipe + restore --------------------------------------------------------
# Streamed, not spooled to a temp file: the production database is multi-GB and
# the server's disk is shared with two sets of Docker images.
echo "==> dropping and recreating the staging schema"
docker exec -i "$stag_db" psql -U plane -d postgres \
  -c "DROP DATABASE IF EXISTS plane WITH (FORCE);" \
  -c "CREATE DATABASE plane OWNER plane;"

echo "==> streaming production dump into staging (this takes a while)"
# pg_dump runs in the STAGING container because that is where a pg17 client
# lives; it connects OUT to Neon. Production has no local postgres to exec into.
docker exec -i -e PGURL="$PROD_DB_URL" "$stag_db" \
  sh -c 'pg_dump --no-owner --no-acl "$PGURL"' \
  | docker exec -i "$stag_db" psql -U plane -d plane -v ON_ERROR_STOP=1 -q

echo "==> ensuring pgvector is present (ai_ext needs it)"
docker exec -i "$stag_db" psql -U plane -d plane -c "CREATE EXTENSION IF NOT EXISTS vector;"

# --- bring the restored schema up to this checkout's migration state -------
# This is the whole point of the rehearsal: real rows, this branch's migrations.
echo "==> running staging migrator against the restored data"
docker compose -p "$STAGING_PROJECT" -f "$STAGING_DIR/docker-compose.yaml" \
  --env-file="$STAGING_DIR/plane.env" run --rm migrator

echo "==> clone complete: Neon -> $STAGING_PROJECT"
echo "    Production was never written to."
