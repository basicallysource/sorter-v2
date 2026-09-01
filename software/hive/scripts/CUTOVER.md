# Hive deploy cutover — record of what was done, 2026-08-07

**This is history, not a runbook. It has already been carried out — do not run
it.** It records how Hive moved from "build on the prod box from a git checkout"
to "CI builds images, prod installs published releases", on 2026-08-07. Kept
because the reasoning and the recovery procedures are still worth having.

- **To deploy Hive today:** push a tag — `software/hive/scripts/release.sh`. See
  [README.md](README.md), which is the current operational doc.
- **To stand up a brand-new Hive host:** the steps below are still broadly the
  shape of it, but read them as a description rather than a script — versions,
  paths and the two deviations noted below have moved on.

`hive/v0.1.0` was the first release cut this way and went live 2026-08-07
(commit `7edd14ea`).

**Host:** `root@100.116.70.1` (tailnet `balloon`). SSH is tailnet-only; there is
no inbound tcp/22, and 80/443 accept Cloudflare ranges only, so the public IP
is not reachable directly. See
`sorter-v2-agent-notes/documentation/projects/hive/prod-access.md`.

**Nothing here restarted Postgres.** The database container was never touched,
before or after cutover — it has held its uptime straight through.

## Where this was deviated from, and why

Two things below were **not** done as written. The text is left in place so the
reasoning is still legible, with the actual outcome marked at each spot.

| Step | Written as | Actually done |
|---|---|---|
| 1.3 | Make both GHCR packages **public** | **Kept private.** The box got a read-only credential instead — see 1.3. |
| 2.5 | `HIVE_BACKUP_KEEP_DAYS=30`, `KEEP_MIN=7` | **3 and 3.** The off-box copy is the durable one — see 2.5. |

---

## 0. What was there before the cutover

*Historical snapshot — state as of 2026-08-07, **pre-cutover**. None of this
describes the box today.*

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

### 1.3 Package visibility — NOT done as written

> **DEVIATION. The packages were kept PRIVATE.** The instruction below to make
> them public was not followed. Do not "fix" the packages by making them public
> — that would undo a deliberate decision.
>
> What was actually done: visibility left private, and the box was given a
> read-only credential.
>
> - A classic PAT with **only `read:packages`**.
> - `docker login ghcr.io` on prod, stored in root-only
>   `/root/.docker/config.json` (mode 600).
> - The same token set as **`HIVE_GITHUB_TOKEN`** in `/etc/hive-release.env`
>   (mode 600) — note the name, `HIVE_GITHUB_TOKEN`, which is what
>   `hive_release_agent.py` reads. This also authenticates the releases API and
>   so lifts polling off the anonymous 60 requests/hour rate limit, which a
>   60-second timer would otherwise sit uncomfortably close to.
>
> Verify it is still private — this should print `403`:
>
> ```bash
> tok=$(curl -s "https://ghcr.io/token?scope=repository:basicallysource/hive-backend:pull&service=ghcr.io" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
> curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $tok" \
>   https://ghcr.io/v2/basicallysource/hive-backend/manifests/v0.1.0
> ```

*Original text, not followed:*

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

### 1.4 Who can cut a release

Repository ruleset **"Release tags — maintainers and admins only"** restricts
creating `hive/v*`, `firmware/v*` and `sorteros/v*` tags to maintainers and
admins, and blocks their deletion. Deploy rights are therefore not the same
thing as write access to the repo — someone can merge to `main` without being
able to ship it.

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
# NOTE: the 30/7 above were overridden to 3/3 by the second block below.
# The live values are 3 and 3 — see the DEVIATION note there.
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

> **DEVIATION (retention).** These last two lines are the ones that took effect
> — **3 days, floor of the 3 newest**, not the 30/7 written in the first block.
> Verified live: `HIVE_BACKUP_KEEP_DAYS=3`, `HIVE_BACKUP_KEEP_MIN=3`. The code's
> own defaults are 30/7; the box deliberately does not use them. Short on
> purpose — 30 days of dumps is ~9 GB on a 77 GB disk that was already at 76%,
> and the off-box Space is the durable copy. The Spaces key is `hive-backups-rw`,
> scoped `readwrite` to `sorter-hive-backups` only; the bucket is private
> (anonymous GET → 403).

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

Prod must be running CI's build and not a local one. Note that `docker ps`
shows a bare image **ID** here, not the `ghcr.io/...@sha256:...` reference —
an image pulled by digest carries no tag for `docker ps` to print. Ask
`docker inspect` for the real reference:

```bash
docker inspect hive-backend hive-frontend --format '{{.Name}} {{.Config.Image}}'
```

That prints `ghcr.io/basicallysource/hive-backend@sha256:...`, which is the
actual proof. Then click through the site: log in, open a sorting profile, load
a labeling page (exercises Postgres and S3).

### 2.9 Arm the timer

Only after 2.8 passes:

```bash
systemctl enable --now hive-release.timer
systemctl list-timers hive-release.timer --no-pager
journalctl -u hive-release -f     # ctrl-c when you've seen a quiet poll
```

From here, `software/hive/scripts/release.sh vX.Y.Z` is the entire deploy.

### 2.10 Decommission the old path — STILL OUTSTANDING

> **Not done.** As of 2026-08-07 the old on-box images
> (`hive-{backend,frontend}:{latest,rollback}`) and
> `data.fresh-empty-20260609/` are all still present. Nothing depends on them
> and nothing breaks by leaving them; disk is at 70% (24 G free), so the
> pressure that motivated this has eased. Still worth reclaiming eventually.

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

## Move the data out of the git checkout — STILL OUTSTANDING

> **Not done.** `HIVE_DATA_DIR` is still
> `/basically/sorter/sorter-v2/software/hive/data` — the live Postgres data
> directory remains inside the git checkout. This is the arrangement that caused
> the 2026-06-09 wipe. Removing git from the deploy path (which *is* done)
> closes the path that actually triggered it, but not the arrangement itself.
> Moving it is agreed and deferred. Tracked in
> `sorter-v2-agent-notes/documentation/projects/hive/backups.md`.

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

A deploy whose release changes `alembic/versions` writes a `*-predeploy.dump`
**before** it migrates, so the dump matching the schema you want back is always
the one taken by the deploy that broke it. Deploys with no migration changes
skip the dump on purpose — an app-only deploy is undone by `rollback`, not a
restore, and the nightly + off-box copies cover data loss. The agent decides by
comparing the `migrations` fingerprint in `hive-release.json` against the
running release's; a release without the field always dumps.

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
