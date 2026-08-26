#!/usr/bin/env bash
#
# Clone the PRODUCTION Plane database into the STAGING stack, on demand.
#
# Staging normally starts empty — that is deliberate, because a from-zero
# migration is the thing an upstream rebase most often breaks. This script
# exists for the other case: rehearsing a migration against real row volumes
# before it runs on production.
#
#   Source: compose project `plane-fork-app`     (production) — READ ONLY
#   Target: compose project `plane-staging-app`  (staging)    — WIPED
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
#     `pg_dump`. There is no psql/restore path anywhere in this script that
#     targets PROD_PROJECT, so the direction cannot be inverted by swapping an
#     argument — you would have to add a write path that does not exist.
#   * The target is a hardcoded literal that is asserted, never a parameter.
#     A parameter is the hole; the assertion is the guard.
#   * It refuses if production is not running, so a typo cannot produce an
#     empty dump that wipes staging and restores nothing.
#
set -euo pipefail

PROD_PROJECT="plane-fork-app"
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
    FROM  $PROD_PROJECT      ($PROD_DIR)      -- read only, via pg_dump
    INTO  $STAGING_PROJECT   ($STAGING_DIR)   -- DROPPED AND RECREATED
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
if [ "$STAGING_PROJECT" = "$PROD_PROJECT" ]; then
  echo "ABORT: source and target are the same project."
  exit 1
fi

# --- guard 3: both stacks must actually be up ------------------------------
prod_db="$(docker compose -p "$PROD_PROJECT" ps -q plane-db 2>/dev/null || true)"
stag_db="$(docker compose -p "$STAGING_PROJECT" ps -q plane-db 2>/dev/null || true)"

if [ -z "$prod_db" ]; then
  echo "ABORT: production database container not running under project '$PROD_PROJECT'."
  echo "       A missing source would produce an empty dump and wipe staging for nothing."
  exit 1
fi
if [ -z "$stag_db" ]; then
  echo "ABORT: staging database container not running under project '$STAGING_PROJECT'."
  echo "       Deploy staging first, then re-run this."
  exit 1
fi

echo "==> prod  plane-db: $prod_db"
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
docker exec -i "$prod_db" pg_dump -U plane -d plane --no-owner --no-acl \
  | docker exec -i "$stag_db" psql -U plane -d plane -v ON_ERROR_STOP=1 -q

echo "==> ensuring pgvector is present (ai_ext needs it)"
docker exec -i "$stag_db" psql -U plane -d plane -c "CREATE EXTENSION IF NOT EXISTS vector;"

# --- bring the restored schema up to this checkout's migration state -------
# This is the whole point of the rehearsal: real rows, this branch's migrations.
echo "==> running staging migrator against the restored data"
docker compose -p "$STAGING_PROJECT" -f "$STAGING_DIR/docker-compose.yaml" \
  --env-file="$STAGING_DIR/plane.env" run --rm migrator

echo "==> clone complete: $PROD_PROJECT -> $STAGING_PROJECT"
echo "    Production was never written to."
