# Hive ops: release & backup

Prod host: `root@100.116.70.1` (tailscale, hostname `balloon`; the public IP
45.55.232.164 serves only 80/443, so you must be on the tailnet to poke at the
box) · deploy root `/basically/hive` · stack traefik + hive-backend +
hive-frontend + hive-postgres. Sample **images live in S3**; the **DB** (sample
metadata, models, users, reviews) and **parts.db** live on the droplet.

## Deploy

```bash
software/hive/scripts/release.sh v0.2.0     # or with no arg: auto-bump patch
```

That is the whole thing. It tags `hive/v0.2.0` and pushes;
`.github/workflows/hive-release.yml` builds both images, pushes them to GHCR,
and publishes a GitHub Release carrying a digest-pinned manifest. Prod polls
that release list every minute (`hive-release.timer`) and installs on its own,
typically within a minute of the workflow finishing.

Nothing is built on the prod box. Nothing is scp'd to it. There is no `deploy.sh`.

Watch it land:

```bash
ssh root@100.116.70.1 'journalctl -u hive-release -f'
ssh root@100.116.70.1 'python3 /usr/local/lib/hive/hive_release_agent.py status'
```

Each install, in order: verify `hive-postgres` healthy → **verified `pg_dump`**
→ pull both images by digest → `alembic upgrade head` with the new image while
the old one still serves → recreate backend+frontend → confirm both containers
actually restarted → health-check containers *and* the public URL → record
state. Any failure rolls back to the previously installed digests.

`hive-postgres` is never recreated by a deploy (`--no-deps`).

**Setting this up on a fresh box, or cutting over from the old build-on-prod
deploy: see [CUTOVER.md](CUTOVER.md).**

## Break-glass

Run on prod (`ssh root@100.116.70.1`):

```bash
python3 /usr/local/lib/hive/hive_release_agent.py status
python3 /usr/local/lib/hive/hive_release_agent.py rollback
python3 /usr/local/lib/hive/hive_release_agent.py install --version v0.1.3
python3 /usr/local/lib/hive/hive_release_agent.py backup --reason manual
systemctl stop hive-release.timer          # pause deploys
```

Rolling back re-pulls the previous digests; it does **not** revert migrations.
If the schema is the problem, restore the `*-predeploy.dump` the failing deploy
wrote — see CUTOVER.md → "Restoring the database".

## Backup strategy

| Layer | What | Where | Cadence |
|-------|------|-------|---------|
| Pre-deploy | agent dumps + verifies before migrating; deploy aborts if it fails | `/basically/backups/hive-db/db-*-predeploy.dump` | every deploy |
| Nightly | `hive-backup.timer` → same verified dump | `/basically/backups/hive-db/db-*-nightly.dump` | 03:15 daily |
| Off-box (opt) | same dump uploaded | `$HIVE_BACKUP_S3_PREFIX` | with each dump |
| Off-box (manual) | `backup.sh` pulls DB + parts.db to your Mac | `./backups/` | on demand |
| Images | app writes originals | S3 bucket | continuous |

Every dump is validated with `pg_restore --list`, not just a size check — a
`pg_dump` whose pipe broke still exits 0 and still writes a nonzero file.
Retention is 30 days but never fewer than the 7 newest dumps, so a quiet month
cannot leave the directory empty.

Restore:

```bash
docker exec -i hive-postgres sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists' \
  < /basically/backups/hive-db/db-<stamp>-predeploy.dump
```

> Note: before 2026-08 the nightly backup documented here was a cron line that
> had **never actually been installed** — `crontab -l` was empty and
> `/basically/backups/hive-db` did not exist. The only backups that existed were
> the ones `deploy.sh` happened to pull to a Mac. It is a systemd timer now,
> which is checkable: `systemctl list-timers hive-backup.timer`.

## Data location

The live Postgres datadir, parts.db, uploads and model files are bind-mounted
from `${HIVE_DATA_DIR}` (set in `/basically/hive/.env.prod`). Deploys no longer
touch a git checkout at all, so the 2026-06-09 failure mode below cannot recur
through the deploy path — but until the optional move in CUTOVER.md is done, the
data still physically sits inside `/basically/sorter/sorter-v2`. **Never run
`git clean`, `git stash -u`, or `git reset --hard` in that checkout.**

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

The real fix landed 2026-08: git is no longer part of deploying, so no deploy
step can move the datadir.
