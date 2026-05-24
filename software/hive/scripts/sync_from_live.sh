#!/usr/bin/env bash
#
# Mirror live Hive into the local dev environment: Postgres dump + restore,
# plus S3 bucket → local UPLOAD_DIR sync. Lets us iterate locally against
# real samples without burning roundtrips to prod.
#
# Usage:
#   ./sync_from_live.sh              # both db + s3
#   ./sync_from_live.sh db           # db only
#   ./sync_from_live.sh s3           # s3 only
#   ./sync_from_live.sh --dry-run    # print sizes + counts, change nothing
#
# Prereqs: ssh access to LIVE_HOST, local docker postgres running (services
# from software/hive/docker-compose.yml), aws CLI installed locally. The
# script pulls S3 credentials from the live container env at runtime — no
# secrets are stored in this file.
#
# Re-runnable. The DB phase uses pg_restore --clean --if-exists so it
# replaces local data wholesale. S3 sync skips unchanged objects.

set -euo pipefail

# ------------------------------------------------------------------ config

LIVE_HOST="${LIVE_HOST:-root@45.55.232.164}"
LIVE_REPO="${LIVE_REPO:-/basically/sorter/sorter-v2/software/hive}"
LIVE_BACKEND_CONTAINER="${LIVE_BACKEND_CONTAINER:-hive-backend}"
LIVE_PG_CONTAINER="${LIVE_PG_CONTAINER:-hive-postgres}"

LOCAL_PG_CONTAINER="${LOCAL_PG_CONTAINER:-hive-postgres-1}"
LOCAL_UPLOAD_DIR="${LOCAL_UPLOAD_DIR:-$(cd "$(dirname "$0")/.." && pwd)/backend/data/uploads}"

DUMP_REMOTE="/tmp/hive_live.dump"
DUMP_LOCAL="${TMPDIR:-/tmp}/hive_live.dump"

DRY_RUN=0
PHASE="all"

# ------------------------------------------------------------------ helpers

color()  { printf "\033[1;%sm%s\033[0m\n" "$1" "$2"; }
info()   { color 36 "▸ $*"; }
ok()     { color 32 "✓ $*"; }
warn()   { color 33 "! $*"; }
die()    { color 31 "✗ $*" >&2; exit 1; }

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    color 90 "  [dry-run] $*"
  else
    "$@"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

# ------------------------------------------------------------------ args

for arg in "$@"; do
  case "$arg" in
    db|s3|all) PHASE="$arg" ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      grep -E '^#( |$)' "$0" | sed -E 's/^# ?//'
      exit 0
      ;;
    *) die "unknown arg: $arg (try --help)" ;;
  esac
done

# ------------------------------------------------------------------ preflight

require_cmd ssh
require_cmd docker
require_cmd scp
if [[ "$PHASE" == "s3" || "$PHASE" == "all" ]]; then
  require_cmd aws || die "aws CLI not found. Install: brew install awscli"
fi

# Local pg container has to be up so pg_restore can talk to it.
if [[ "$PHASE" == "db" || "$PHASE" == "all" ]]; then
  docker ps --format '{{.Names}}' | grep -q "^${LOCAL_PG_CONTAINER}$" \
    || die "local postgres container '${LOCAL_PG_CONTAINER}' not running — start it with: docker compose -f software/hive/docker-compose.yml up -d postgres"
fi

# ------------------------------------------------------------------ snapshot of live state

info "Probing live state…"
read_remote_env() {
  ssh "$LIVE_HOST" "docker exec $LIVE_BACKEND_CONTAINER printenv $1" 2>/dev/null | tr -d '\r\n'
}

LIVE_PG_USER=$(read_remote_env POSTGRES_USER || true)
LIVE_PG_DB=$(read_remote_env POSTGRES_DB || true)
# Backend uses DATABASE_URL parsed at startup; PG_USER/DB env vars live on the
# postgres container itself. Fall back to known defaults so this still works on
# a freshly-restarted backend that hasn't re-injected them.
if [[ -z "$LIVE_PG_USER" || -z "$LIVE_PG_DB" ]]; then
  LIVE_PG_USER=$(ssh "$LIVE_HOST" "docker exec $LIVE_PG_CONTAINER printenv POSTGRES_USER" | tr -d '\r\n')
  LIVE_PG_DB=$(ssh "$LIVE_HOST" "docker exec $LIVE_PG_CONTAINER printenv POSTGRES_DB" | tr -d '\r\n')
fi

S3_BUCKET=$(read_remote_env S3_BUCKET)
S3_ENDPOINT_URL=$(read_remote_env S3_ENDPOINT_URL)
S3_REGION=$(read_remote_env S3_REGION)
S3_ACCESS_KEY_ID=$(read_remote_env S3_ACCESS_KEY_ID)
S3_SECRET_ACCESS_KEY=$(read_remote_env S3_SECRET_ACCESS_KEY)

[[ -n "$LIVE_PG_USER" && -n "$LIVE_PG_DB" ]] || die "could not read live PG user/db"
[[ -n "$S3_BUCKET" && -n "$S3_ENDPOINT_URL" ]] || die "could not read live S3 settings"

DB_SIZE=$(ssh "$LIVE_HOST" "docker exec $LIVE_PG_CONTAINER psql -U $LIVE_PG_USER -d $LIVE_PG_DB -tAc \"SELECT pg_size_pretty(pg_database_size('$LIVE_PG_DB'))\"" | tr -d '\r\n')
SAMPLE_COUNT=$(ssh "$LIVE_HOST" "docker exec $LIVE_PG_CONTAINER psql -U $LIVE_PG_USER -d $LIVE_PG_DB -tAc 'SELECT COUNT(*) FROM samples'" | tr -d '\r\n')

ok "live db: $LIVE_PG_USER@$LIVE_PG_DB ($DB_SIZE, $SAMPLE_COUNT samples)"
ok "live s3: s3://$S3_BUCKET @ $S3_ENDPOINT_URL"

if [[ "$PHASE" == "s3" || "$PHASE" == "all" ]]; then
  info "Tallying S3 bucket size (may take a few seconds)…"
  S3_SIZE_LINE=$(AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
    aws --endpoint-url "$S3_ENDPOINT_URL" --region "$S3_REGION" \
      s3 ls --recursive --summarize "s3://$S3_BUCKET/" | tail -2)
  ok "s3 contents:"
  echo "$S3_SIZE_LINE" | sed 's/^/    /'
fi

# ------------------------------------------------------------------ db phase

sync_db() {
  info "Dumping live DB to ${DUMP_REMOTE} on ${LIVE_HOST}…"
  run ssh "$LIVE_HOST" "docker exec $LIVE_PG_CONTAINER pg_dump -Fc --no-owner --no-privileges -U $LIVE_PG_USER -d $LIVE_PG_DB > $DUMP_REMOTE"

  info "Copying dump to ${DUMP_LOCAL}…"
  run scp "$LIVE_HOST:$DUMP_REMOTE" "$DUMP_LOCAL"
  if [[ $DRY_RUN -eq 0 ]]; then
    ok "dump size: $(du -h "$DUMP_LOCAL" | awk '{print $1}')"
  fi

  # Local postgres container env (matches docker-compose.yml in this dir).
  local_pg_user=$(docker exec "$LOCAL_PG_CONTAINER" printenv POSTGRES_USER | tr -d '\r\n')
  local_pg_db=$(docker exec "$LOCAL_PG_CONTAINER" printenv POSTGRES_DB | tr -d '\r\n')
  info "Restoring into local $local_pg_user@$local_pg_db (drops existing data)…"
  # --clean --if-exists drops every object before recreating, so a partial prior
  # restore can't leave stale rows behind. The redirect (< dumpfile) is set up
  # by the shell before run() is called, so guard the whole thing on DRY_RUN.
  if [[ $DRY_RUN -eq 1 ]]; then
    color 90 "  [dry-run] docker exec -i $LOCAL_PG_CONTAINER pg_restore --clean --if-exists -U $local_pg_user -d $local_pg_db < $DUMP_LOCAL"
  else
    docker exec -i "$LOCAL_PG_CONTAINER" pg_restore --clean --if-exists --no-owner --no-privileges \
      -U "$local_pg_user" -d "$local_pg_db" < "$DUMP_LOCAL"
  fi

  ok "DB restored"
  warn "Encrypted columns (api keys, magic links) only decrypt if your local SECRET_ENCRYPTION_KEY matches the live one. Copy it from live's .env.prod into backend/.env if you need to use those features."
}

# ------------------------------------------------------------------ s3 phase

sync_s3() {
  info "Syncing s3://$S3_BUCKET → $LOCAL_UPLOAD_DIR (skips unchanged objects)…"
  mkdir -p "$LOCAL_UPLOAD_DIR"
  # --no-progress keeps the log readable; --size-only is faster than mtime
  # checks against DO Spaces which sometimes drifts.
  run env \
    AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
    aws --endpoint-url "$S3_ENDPOINT_URL" --region "$S3_REGION" \
      s3 sync --no-progress --size-only \
        "s3://$S3_BUCKET/" "$LOCAL_UPLOAD_DIR/"
  ok "S3 synced into $LOCAL_UPLOAD_DIR"
}

# ------------------------------------------------------------------ run

case "$PHASE" in
  db) sync_db ;;
  s3) sync_s3 ;;
  all) sync_db; sync_s3 ;;
esac

ok "Done."
