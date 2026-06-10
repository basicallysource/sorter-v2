# Hive ops: deploy & backup

Prod host: `root@45.55.232.164` · repo `/basically/sorter/sorter-v2` · stack
`software/hive/docker-compose.prod.yml` (traefik + hive-backend + hive-frontend +
hive-postgres). Sample **images live in S3**; the **DB** (sample metadata,
models, users, reviews) and **parts.db** live on the droplet.

## Deploy (from your local machine)

```bash
software/hive/scripts/deploy.sh [branch]      # default branch: sorthive
```

What it does, in order: abort if prod has uncommitted **tracked** changes →
`pg_dump` to `./backups/` → `git reset --hard origin/<branch>` (tracked files
only) → `docker compose build` → `alembic upgrade head` → `up -d` → health-check
`/api/models`; **rolls back** to the previous SHA on failure.

It deliberately **never** runs `git stash -u` or `git clean` — see post-mortem.

## Backup strategy

| Layer | What | Where | Cadence |
|-------|------|-------|---------|
| On-box | `pg-backup.sh` → `pg_dump -Fc` | `/basically/backups/hive-db` (+ S3 if configured) | daily cron 03:15 |
| Off-box | `backup.sh` pulls DB + parts.db | your Mac `./backups/` | on demand / before deploy |
| Pre-deploy | `deploy.sh` auto-dumps | your Mac `./backups/` | every deploy |
| Images | app writes originals | S3 bucket | continuous |

Server cron (`crontab -e` on prod):
```
15 3 * * * /basically/sorter/sorter-v2/software/hive/scripts/pg-backup.sh >> /var/log/hive-pg-backup.log 2>&1
```
Set `HIVE_BACKUP_S3_PREFIX=s3://<bucket>/hive-db` (+ aws cli/creds) for off-box copies.

**Restore** a dump into the running DB:
```bash
docker exec -i hive-postgres sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists' < backups/db-<ts>.dump
```

## Data location (and the landmine)

The prod postgres datadir + parts.db are bind-mounted from `software/hive/data/`
— **inside the repo working tree**. They are now `.gitignore`d (`/data/`) so git
treats them as off-limits. **Hardening TODO:** move them out of the repo entirely
to `/basically/hive-data/` and point the compose mounts there (parameterize with
`HIVE_DATA_DIR`), so repo and live data are physically separate. Runbook:

```bash
# on prod, with the stack stopped and a fresh backup in hand:
cd /basically/sorter/sorter-v2/software/hive
docker compose --env-file .env.prod -f docker-compose.prod.yml down
mkdir -p /basically/hive-data && mv data/* /basically/hive-data/
echo 'HIVE_DATA_DIR=/basically/hive-data' >> .env.prod   # compose mounts read ${HIVE_DATA_DIR:-./data}
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
# verify: site 200 + select count(*) from samples
```

## Post-mortem — 2026-06-09 DB wipe (recovered)

A manual deploy ran `git stash -u` to clear prod's uncommitted changes before a
fast-forward. Because `software/hive/data/` was untracked **and not gitignored**,
`stash -u` moved the live postgres datadir into the stash. Postgres kept serving
from open FDs until it restarted, then came up on an empty cluster (site 500/502).
Recovery: stop containers → restore the datadir from the stash (`git checkout
stash^3 -- …`, which also dropped postgres' empty runtime dirs and reset
ownership) → recreate the missing empty dirs from a fresh init skeleton →
`chown 70:70` (postgres) and `chown 100:101` (the `app` user, for
uploads/profile_builder) → start → WAL crash-recovery → all 22k samples back.

Fixes landed: `/data/` gitignored; `deploy.sh` never stashes/cleans and backs up
first; backup strategy above. Open: physically move data out of the repo.
