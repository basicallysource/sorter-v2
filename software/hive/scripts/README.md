# Hive ops: release & backup

Prod host: `root@100.116.70.1` (tailscale, hostname `balloon`) · deploy root
`/basically/hive` · stack traefik + hive-backend + hive-frontend +
hive-postgres. Sample **images live in S3**; the **DB** (sample metadata,
models, users, reviews) and **parts.db** live on the droplet.

**SSH is tailnet-only** — there is no inbound tcp/22 at all, and 80/443 accept
Cloudflare ranges only, so the public IP is not reachable directly. Machines
talk to Hive at `https://hive.basically.website` through Cloudflare and do
**not** need to be on the tailnet; the tailnet is for administration. Details:
`sorter-v2-agent-notes/documentation/projects/hive/prod-access.md`.

## Deploy

```bash
software/hive/scripts/release.sh v0.2.0     # or with no arg: auto-bump patch
```

That is the whole thing. It tags `hive/v0.2.0` and pushes;
`.github/workflows/hive-release.yml` builds both images, pushes them to GHCR,
and publishes a GitHub Release carrying a digest-pinned manifest. Prod polls
that release list every minute (`hive-release.timer`) and installs on its own,
typically within a minute of the workflow finishing.

Nothing is built on the prod box. Nothing is scp'd to it. No git command runs
against the prod checkout as part of deploying. There is no `deploy.sh`.

Two things worth knowing before you try to ship:

- **Only maintainers and admins can cut a release.** The repository ruleset
  "Release tags — maintainers and admins only" restricts creating `hive/v*`
  (also `firmware/v*`, `sorteros/v*`) and blocks deleting them. Write access to
  the repo is not the same as deploy rights.
- **The GHCR packages are private.** Prod does not pull anonymously — it uses a
  classic PAT with only `read:packages`, via `docker login ghcr.io` stored in
  root-only `/root/.docker/config.json`, and the same token as
  `HIVE_GITHUB_TOKEN` in `/etc/hive-release.env` (which also lifts the releases
  API off the anonymous 60/hr rate limit). **Do not make the packages public** —
  private is deliberate.

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

**Old images are pruned after a successful install.** A backend image is
1.36 GB and every release pulls a new one *by digest*, which leaves the old
one untagged but **not dangling** — so `docker image prune` does nothing for
it and they accumulate one per deploy. On 2026-08-09 that took the 77 GB disk
to 96% and killed a deploy at the pre-deploy `pg_dump` with `no space left on
device`: v0.1.9 was built, published, and never installed. The agent now
deletes hive images that no container is using and that are older than
`HIVE_IMAGE_KEEP_HOURS` (48), so a rollback inside that window is a restart
rather than a re-pull. It names the two hive repositories only — never
`prune -a`, which would also take traefik and postgres.

**How this was set up:** [CUTOVER.md](CUTOVER.md) is the record of the
2026-08-07 cutover. It is history — it has been carried out and must not be run
again — but it is the reference for standing up a fresh box and for the
recovery procedures.

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
| Off-box | same dump uploaded; run fails if it does not land | `$HIVE_BACKUP_S3_BUCKET` | with each dump |
| Off-box (manual) | `backup.sh` pulls DB + parts.db to your Mac | `./backups/` | on demand |
| Images | app writes originals | S3 bucket | continuous |

Every dump is validated with `pg_restore --list`, not just a size check — a
`pg_dump` whose pipe broke still exits 0 and still writes a nonzero file.

Local retention is **3 days, never fewer than the 3 newest dumps**
(`HIVE_BACKUP_KEEP_DAYS=3`, `HIVE_BACKUP_KEEP_MIN=3` in `/etc/hive-release.env`).
Note the code's own defaults are 30/7 — the box deliberately overrides them.
Short on purpose: 30 days is ~9 GB on a 77 GB disk, and the **off-box copy is
the durable one**. That is also why the S3 upload is required rather than
best-effort — a backup run whose upload fails exits non-zero, because short
local retention plus a silently-failing upload is how you end up with no
backups and no signal.

The Space is `sorter-hive-backups` (nyc3, **private** — anonymous GET returns
403), written with a Spaces key `hive-backups-rw` scoped `readwrite` to that
bucket **only**: a credential that writes backups must not also be able to
delete them, or one leak takes the data and the recovery path together.

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
through the deploy path — but that move **has not been done**: `HIVE_DATA_DIR`
is still `/basically/sorter/sorter-v2/software/hive/data`, so the live datadir
physically sits inside the checkout. **Never run `git clean`, `git stash -u`, or
`git reset --hard` in that checkout.**

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
