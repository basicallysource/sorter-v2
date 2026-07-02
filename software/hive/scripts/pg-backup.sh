#!/usr/bin/env bash
# Server-side scheduled DB backup. Runs ON the prod host (cron).
#
#   crontab -e:
#     15 3 * * * /basically/sorter/sorter-v2/software/hive/scripts/pg-backup.sh >> /var/log/hive-pg-backup.log 2>&1
#
# Dumps the DB to a host directory with retention. If the AWS CLI + S3_* env are
# present it also uploads the dump off-box (a droplet loss otherwise loses the
# local dumps — sample images already live in S3).
set -euo pipefail

BACKUP_DIR="${HIVE_BACKUP_DIR:-/basically/backups/hive-db}"
KEEP_DAYS="${HIVE_BACKUP_KEEP_DAYS:-30}"
S3_PREFIX="${HIVE_BACKUP_S3_PREFIX:-}"      # e.g. s3://my-bucket/hive-db  (empty = skip)

mkdir -p "$BACKUP_DIR"
ts="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/db-$ts.dump"

docker exec hive-postgres sh -c 'pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB' > "$out"
test -s "$out" || { echo "$(date -Is) FAIL: empty dump" >&2; rm -f "$out"; exit 1; }
echo "$(date -Is) ok $out ($(du -h "$out" | cut -f1))"

# Off-box copy (best-effort)
if [ -n "$S3_PREFIX" ] && command -v aws >/dev/null 2>&1; then
  aws s3 cp "$out" "$S3_PREFIX/db-$ts.dump" && echo "$(date -Is) uploaded $S3_PREFIX/db-$ts.dump"
fi

# Retention
find "$BACKUP_DIR" -name 'db-*.dump' -mtime "+$KEEP_DAYS" -delete
