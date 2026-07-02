#!/usr/bin/env bash
# Deploy Hive (backend + frontend) to the prod host — run from your LOCAL machine.
#
#   software/hive/scripts/deploy.sh [branch]      # branch default: sorthive
#
# Safe by construction (see the 2026-06-09 data-loss post-mortem):
#   - The prod postgres datadir + parts.db live inside the repo working tree at
#     software/hive/data/ (gitignored). This script therefore NEVER runs
#     `git stash -u` / `git clean` — those would wipe the live database.
#   - Code is updated with `git reset --hard origin/<branch>`, which only touches
#     TRACKED files and leaves the ignored data/ dir alone.
#   - Aborts if the prod repo has uncommitted TRACKED changes (never auto-stashes).
#   - pg_dumps the DB to ./backups/ BEFORE migrating.
#   - Records the live SHA and rolls back if the post-deploy health check fails.
set -euo pipefail

HOST="${HIVE_HOST:-root@45.55.232.164}"
REPO="${HIVE_REPO:-/basically/sorter/sorter-v2}"
BRANCH="${1:-${HIVE_BRANCH:-sorthive}}"
HEALTH_URL="${HIVE_HEALTH_URL:-https://hive.basically.website/api/models?page_size=1}"
HIVE_DIR="$REPO/software/hive"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_BACKUPS="$(cd "$here/../../.." && pwd)/backups"   # repo-root/backups (gitignored)
ts="$(date +%Y%m%d-%H%M%S)"

echo "▶ Deploy '$BRANCH' → $HOST"

# 1. Pre-flight: refuse if prod has uncommitted TRACKED changes.
ssh "$HOST" "cd '$REPO' && { git diff --quiet && git diff --cached --quiet; }" \
  || { echo "✗ ABORT: prod has uncommitted tracked changes — resolve manually:"; \
       ssh "$HOST" "cd '$REPO' && git status -s"; exit 3; }
echo "  ✓ prod working tree clean (tracked files)"

# 2. Back up the DB to local BEFORE touching anything.
mkdir -p "$LOCAL_BACKUPS"
echo "  • DB backup → backups/db-$ts.dump"
ssh "$HOST" "docker exec hive-postgres sh -c 'pg_dump -U \$POSTGRES_USER -Fc \$POSTGRES_DB'" \
  > "$LOCAL_BACKUPS/db-$ts.dump"
test -s "$LOCAL_BACKUPS/db-$ts.dump" || { echo "✗ ABORT: DB backup is empty"; exit 4; }
echo "  ✓ backup $(du -h "$LOCAL_BACKUPS/db-$ts.dump" | cut -f1)"

# 3. Remote: update code (tracked only) → build → migrate → up → health-check → rollback.
ssh "$HOST" 'bash -s' "$BRANCH" "$REPO" "$HIVE_DIR" "$HEALTH_URL" <<'REMOTE'
set -euo pipefail
BRANCH="$1"; REPO="$2"; HIVE_DIR="$3"; HEALTH_URL="$4"
COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"

cd "$REPO"
PREV="$(git rev-parse HEAD)"; echo "  rollback point: ${PREV:0:9}"
git fetch --quiet origin "$BRANCH"
git reset --hard "origin/$BRANCH"          # tracked files only; ignored data/ untouched
echo "  ✓ code @ $(git rev-parse --short HEAD)"

cd "$HIVE_DIR"
$COMPOSE build backend frontend
$COMPOSE run --rm backend alembic upgrade head    # explicit, visible migration
# --force-recreate: `up -d` alone won't replace a running container when the
# rebuilt image keeps the same :latest tag, so it would silently keep old code.
$COMPOSE up -d --force-recreate backend frontend

echo "  • health check…"
ok=0
for _ in $(seq 1 20); do
  curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && { ok=1; break; }
  sleep 3
done
if [ "$ok" != 1 ]; then
  echo "  ✗ health check FAILED — rolling back to ${PREV:0:9}"
  cd "$REPO" && git reset --hard "$PREV"
  cd "$HIVE_DIR" && $COMPOSE build backend frontend && $COMPOSE up -d
  exit 5
fi
echo "  ✓ healthy @ $(git -C "$REPO" rev-parse --short HEAD)"
REMOTE

echo "▶ Deploy OK"
