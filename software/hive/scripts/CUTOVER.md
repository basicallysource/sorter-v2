# Hive deploy cutover runbook

Moves Hive from "build on the prod box from a git checkout" to "CI builds
images, prod installs published releases". Run top to bottom. Every command is
literal — nothing here is left as an exercise.

**Host:** `root@100.116.70.1` (tailnet `balloon`; public `45.55.232.164` serves
only 80/443, so you must be on the tailnet).
**Nothing in this runbook restarts Postgres.** The database container is never
touched, before or after cutover.

---

## 0. What is there today (verified 2026-08-07, read-only)

| | |
|---|---|
| Checkout | `/basically/sorter/sorter-v2` on `main`, clean except an untracked `software/hive/data.fresh-empty-20260609/` |
| Stack | compose project `hive`, file `/basically/sorter/sorter-v2/software/hive/docker-compose.prod.yml` |
| Containers | `hive-backend`, `hive-frontend`, `hive-postgres` (+ separate `hive-staging-*` project, unrelated, leave alone) |
| Images | `hive-backend:latest`, `hive-frontend:latest`, **built on the box**; someone has been hand-tagging `:rollback` |
| Live data | `/basically/sorter/sorter-v2/software/hive/data` — postgres (2.0G), profile_builder (135M), uploads, color_models, link_models. **Inside the repo working tree.** |
| Secrets | `/basically/sorter/sorter-v2/software/hive/.env.prod` (28 keys, gitignored) |
| Backups | **None.** `/basically/backups/hive-db` does not exist, `crontab -l` is empty, no timer. The nightly documented in `scripts/README.md` was never installed. |
| Disk | 76% used on `/` (19G free) |

---

## 1. GitHub side

### 1.1 Confirm the org allows Actions to publish packages

`basicallysource/sorter-v2` is public and the workflow requests
`packages: write`, so the automatic `GITHUB_TOKEN` is the only credential
needed — **no PAT, no deploy key, no repo secret to create.**

Verify the org isn't blocking it:

- <https://github.com/organizations/basicallysource/settings/packages> → package
  creation must be allowed for the org.
- <https://github.com/basicallysource/sorter-v2/settings/actions> → "Workflow
  permissions" may stay on the read-only default; the workflow grants itself
  what it needs per-job.

### 1.2 Cut the first release (this creates the packages)

From a clean `main` on your Mac:

```bash
software/hive/scripts/release.sh v0.1.0
```

Watch it: <https://github.com/basicallysource/sorter-v2/actions/workflows/hive-release.yml>

It builds both images, pushes them to GHCR, then publishes the release. That
ordering is deliberate: prod polls for *releases*, so a release that exists is
always one whose images exist.

### 1.3 Make both packages public — REQUIRED

GHCR packages are created **private** even from a public repo. Prod pulls
anonymously, so until you do this, every poll fails with `denied`.

For each of <https://github.com/orgs/basicallysource/packages/container/hive-backend/settings>
and <https://github.com/orgs/basicallysource/packages/container/hive-frontend/settings>:

- "Danger Zone" → **Change visibility** → **Public**.
- While you're there, "Manage Actions access" → add repo `sorter-v2` with the
  **Write** role, so later runs can push new versions.

The images contain only public repo source; `.dockerignore` excludes `.env*`,
and every secret is injected at runtime from `.env.prod`. Nothing sensitive is
in a layer.

Verify from anywhere, no login:

```bash
docker manifest inspect ghcr.io/basicallysource/hive-backend:v0.1.0 >/dev/null && echo PUBLIC_OK
```

> Alternative if you'd rather keep them private: leave visibility alone, create
> a classic PAT with only `read:packages`, and add `HIVE_GHCR_TOKEN=<pat>` to
> `/etc/hive-release.env` plus a `docker login ghcr.io -u <user> --password-stdin`
> on prod. Public is one click and one fewer credential to rotate; prefer it.

---

## 2. Prod side

All commands run as root on `100.116.70.1`.

### 2.1 Take a backup by hand before anything

```bash
mkdir -p /basically/backups/hive-db
docker exec hive-postgres sh -c 'pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB' \
  > /basically/backups/hive-db/db-precutover.dump
docker exec -i hive-postgres pg_restore --list \
  < /basically/backups/hive-db/db-precutover.dump >/dev/null && echo BACKUP_VALID
ls -lh /basically/backups/hive-db/db-precutover.dump
```

Do not continue unless it prints `BACKUP_VALID` and the file is non-trivial
(expect hundreds of MB against a 2.0G datadir).

Pull a copy off the box, from your Mac:

```bash
scp root@100.116.70.1:/basically/backups/hive-db/db-precutover.dump ./backups/
```

### 2.2 Create the deploy directory

The new deploy root is `/basically/hive`. It replaces the git checkout as the
thing that defines what is running.

```bash
mkdir -p /basically/hive/state /basically/hive/releases /basically/backups/hive-db
chmod 700 /basically/hive/state
```

### 2.3 Move the secrets file and pin the data directory

```bash
cp -a /basically/sorter/sorter-v2/software/hive/.env.prod /basically/hive/.env.prod
chmod 600 /basically/hive/.env.prod
```

Append the data-dir pin. **The live data is NOT moved** — this just makes the
compose file reference it by absolute path instead of a path relative to the
git checkout, which is what removes git from the deploy path:

```bash
printf '\nHIVE_DATA_DIR=/basically/sorter/sorter-v2/software/hive/data\n' \
  >> /basically/hive/.env.prod
tail -3 /basically/hive/.env.prod
```

Sanity check that the path is right:

```bash
ls -d /basically/sorter/sorter-v2/software/hive/data/postgres && echo DATA_OK
```

### 2.4 Install the agent

```bash
mkdir -p /usr/local/lib/hive
curl -fsSL -o /usr/local/lib/hive/hive_release_agent.py \
  https://raw.githubusercontent.com/basicallysource/sorter-v2/main/software/hive/scripts/hive_release_agent.py
chmod 644 /usr/local/lib/hive/hive_release_agent.py
python3 -c 'import py_compile; py_compile.compile("/usr/local/lib/hive/hive_release_agent.py", doraise=True)' && echo AGENT_OK
```

### 2.5 Agent configuration

```bash
cat > /etc/hive-release.env <<'EOF'
HIVE_REPO_SLUG=basicallysource/sorter-v2
HIVE_DEPLOY_DIR=/basically/hive
HIVE_BACKUP_DIR=/basically/backups/hive-db
HIVE_BACKUP_KEEP_DAYS=30
HIVE_BACKUP_KEEP_MIN=7
HIVE_HEALTH_URL=https://hive.basically.website/api/health
HIVE_PG_CONTAINER=hive-postgres
HIVE_COMPOSE_PROJECT=hive
EOF
chmod 600 /etc/hive-release.env
```

Off-box backup copies. Uses boto3 (already present on the box) against any
S3-compatible endpoint — DigitalOcean Spaces here. Give the key access to the
backup bucket **only**: if the key that writes backups can also be used to
delete them, a single leaked credential takes your data and your recovery path
together.

Setting `HIVE_BACKUP_S3_BUCKET` makes the upload **required** — a backup run
whose upload fails exits non-zero rather than warning. That is deliberate:
local retention is short because the off-box copy is the durable one, so an
upload that silently fails is how you end up with no backups and no signal.

```bash
cat >> /etc/hive-release.env <<'EOF'
HIVE_BACKUP_S3_BUCKET=sorter-hive-backups
HIVE_BACKUP_S3_ENDPOINT=https://nyc3.digitaloceanspaces.com
HIVE_BACKUP_S3_REGION=nyc3
HIVE_BACKUP_S3_ACCESS_KEY_ID=<spaces key scoped to that bucket>
HIVE_BACKUP_S3_SECRET_ACCESS_KEY=<its secret>
HIVE_BACKUP_KEEP_DAYS=3
HIVE_BACKUP_KEEP_MIN=3
EOF
```

### 2.6 Install the systemd units

```bash
cd /tmp
for u in hive-release.service hive-release.timer hive-backup.service hive-backup.timer; do
  curl -fsSL -o "/etc/systemd/system/$u" \
    "https://raw.githubusercontent.com/basicallysource/sorter-v2/main/software/hive/scripts/systemd/$u"
done
systemctl daemon-reload
```

Turn on the **backup** timer now — it is independent of the deploy cutover and
there is currently no backup at all:

```bash
systemctl enable --now hive-backup.timer
systemctl start hive-backup.service
journalctl -u hive-backup -n 30 --no-pager
ls -lh /basically/backups/hive-db/
```

Expect a `db-<stamp>-nightly.dump` and a `✓ backup ok` line. Leave
`hive-release.timer` **off** for now.

### 2.7 First install, by hand, watching it

This is the actual cutover. It pulls the release images, migrates, and replaces
`hive-backend` / `hive-frontend`. `hive-postgres` is not touched.

```bash
python3 /usr/local/lib/hive/hive_release_agent.py install --version v0.1.0 2>&1 | tee /tmp/hive-cutover.log
```

Expected sequence in the output: `installing v0.1.0` → `backup →` → `✓ backup
ok` → `pulling images by digest` → `alembic upgrade head` → `recreating
services` → `✓ hive-backend recreated` → `✓ hive-frontend recreated` → `✓
healthy` → `✓ v0.1.0 live`.

If it fails it rolls back on its own, or — on this very first install, where
there is no previous release recorded — it prints exactly what to run. In that
case the old stack is recoverable with:

```bash
cd /basically/sorter/sorter-v2/software/hive
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --no-deps backend frontend
```

(the old `:latest` images are still on the box until step 2.10).

### 2.8 Verify

```bash
python3 /usr/local/lib/hive/hive_release_agent.py status
docker ps --filter name=hive- --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
curl -fsS https://hive.basically.website/api/health && echo
```

`docker ps` must now show `ghcr.io/basicallysource/hive-*@sha256:...` as the
images — that is the proof prod is running CI's build and not a local one. Then
click through the site: log in, open a sorting profile, load a labeling page
(exercises Postgres and S3).

### 2.9 Arm the timer

Only after 2.8 passes:

```bash
systemctl enable --now hive-release.timer
systemctl list-timers hive-release.timer --no-pager
journalctl -u hive-release -f     # ctrl-c when you've seen a quiet poll
```

From here, `software/hive/scripts/release.sh vX.Y.Z` is the entire deploy.

### 2.10 Decommission the old path

Only after a *second* release has been cut and installed by the timer on its
own. Nothing here is urgent; the checkout is harmless once it is no longer the
deploy source.

```bash
# free the on-box built images (~3.3G, and the box is at 76%)
docker image rm hive-backend:latest hive-frontend:latest hive-backend:rollback hive-frontend:rollback
# stale empty datadir from the 2026-06-09 incident, confirmed unused
ls -la /basically/sorter/sorter-v2/software/hive/data.fresh-empty-20260609
rm -rf /basically/sorter/sorter-v2/software/hive/data.fresh-empty-20260609
```

Leave `/basically/sorter/sorter-v2` in place — the live `data/` directory is
still inside it (see the optional step below), and other tooling
(`sync_from_live.sh`) references it.

**Never run `git clean`, `git stash -u`, or `git reset --hard` in that checkout
while `data/` lives there.** That is exactly the 2026-06-09 wipe.

---

## Optional (recommended, later): move the data out of the git checkout

Closes the original landmine for good. Needs a few minutes of downtime and a
fresh backup. Do it on its own, not during cutover.

```bash
python3 /usr/local/lib/hive/hive_release_agent.py backup --reason premove
cd /basically/hive
docker compose --project-name hive --env-file .env.prod \
  -f releases/$(python3 -c 'import json;print(json.load(open("state/current.json"))["version"])')/docker-compose.prod.yml \
  down
mkdir -p /basically/hive-data
mv /basically/sorter/sorter-v2/software/hive/data/* /basically/hive-data/
sed -i 's#^HIVE_DATA_DIR=.*#HIVE_DATA_DIR=/basically/hive-data#' /basically/hive/.env.prod
python3 /usr/local/lib/hive/hive_release_agent.py poll --force
```

Ownership must survive the move (`postgres` is uid 70, the app user is 100:101).
`mv` on the same filesystem preserves it; verify with `ls -ln /basically/hive-data`.
Afterwards update `LIVE_REPO` in `scripts/sync_from_live.sh` and `HIVE_REPO` in
`scripts/backup.sh`.

---

## Day-to-day

| Task | Command |
|---|---|
| Ship | `software/hive/scripts/release.sh v0.2.0` (Mac) |
| Watch a deploy | `journalctl -u hive-release -f` |
| What's live | `python3 /usr/local/lib/hive/hive_release_agent.py status` |
| Roll back one version | `python3 /usr/local/lib/hive/hive_release_agent.py rollback` |
| Pin to a specific version | `python3 /usr/local/lib/hive/hive_release_agent.py install --version v0.1.3` |
| Ad-hoc backup | `python3 /usr/local/lib/hive/hive_release_agent.py backup --reason manual` |
| Pause deploys | `systemctl stop hive-release.timer` |

`rollback` and `install --version` both re-pull by digest and re-run the health
check. Neither reverts migrations — see below.

### Restoring the database

```bash
systemctl stop hive-release.timer
docker exec -i hive-postgres sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists' \
  < /basically/backups/hive-db/db-<stamp>-predeploy.dump
python3 /usr/local/lib/hive/hive_release_agent.py rollback
systemctl start hive-release.timer
```

Every deploy writes a `*-predeploy.dump` **before** it migrates, so the dump
matching the schema you want back is always the one taken by the deploy that
broke it.

### Updating the agent itself

The agent is not self-updating on purpose — an installer that rewrites itself
mid-install is a way to lose both. When `hive_release_agent.py` changes in the
repo, re-run step 2.4. Each release also carries the agent as an asset, so the
version a given release was built against is always recoverable.

---

## Why this shape

**Tag push, not "publish a release".** The tag is the single human action;
CI creates the release. A release therefore only exists once its images are in
the registry, so prod can never see a version it cannot install. Publishing the
release by hand would invert that and allow exactly that race.

**Images built in CI, not on prod.** Building on the box meant the artifact was
"whatever that machine happened to compile", with no reproducibility and no
rollback artifact beyond a hand-tagged `:rollback`. It also burned CPU and ~3.3G
of disk on a box at 76% while it served a customer. Digest-pinned images make
"what is running" answerable and rollback a pull instead of a rebuild.

**Prod pulls, CI does not push.** The box takes no inbound connection from
GitHub — no SSH key in repo secrets, no runner, no webhook endpoint, and nothing
to open up. It also matches the pull-based release pattern already running on
this same host for `balloon`. A poll that is missed costs one minute; an inbound
hook that never arrives would cost the whole deploy.

**Git is out of the deploy path.** The old deploy ran `git reset --hard` on a
working tree that physically contains the live Postgres datadir. That is the
2026-06-09 wipe waiting to happen again. Now the deploy touches a registry, a
compose file, and an env file — the checkout is inert.
