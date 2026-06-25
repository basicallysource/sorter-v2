#!/usr/bin/env bash
# Pull a Hive prod backup to your LOCAL machine (DB dump + parts.db).
#
#   software/hive/scripts/backup.sh
#
# Sample IMAGES are stored in S3 (STORAGE_BACKEND=s3), so they are already
# off-box and not included here — this backs up the relational DB (all sample
# metadata, models, users, reviews) and the catalog parts.db.
#
# Keeps the most recent 14 DB dumps locally and prunes older ones.
set -euo pipefail

HOST="${HIVE_HOST:-root@45.55.232.164}"
REPO="${HIVE_REPO:-/basically/sorter/sorter-v2}"
KEEP="${HIVE_BACKUP_KEEP:-14}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$here/../../.." && pwd)/backups"
mkdir -p "$OUT"
ts="$(date +%Y%m%d-%H%M%S)"

echo "• DB dump → backups/db-$ts.dump"
ssh "$HOST" "docker exec hive-postgres sh -c 'pg_dump -U \$POSTGRES_USER -Fc \$POSTGRES_DB'" > "$OUT/db-$ts.dump"
test -s "$OUT/db-$ts.dump" || { echo "✗ empty dump"; rm -f "$OUT/db-$ts.dump"; exit 1; }
echo "  ✓ $(du -h "$OUT/db-$ts.dump" | cut -f1)"

echo "• parts.db → backups/parts-$ts.db"
ssh "$HOST" "cat '$REPO/software/hive/data/profile_builder/parts.db'" > "$OUT/parts-$ts.db" || true

# retention
ls -1t "$OUT"/db-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "$OUT"/parts-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "✓ backup complete (keeping last $KEEP)"

# To restore a dump into a fresh DB:
#   docker exec -i hive-postgres sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists' < backups/db-<ts>.dump
