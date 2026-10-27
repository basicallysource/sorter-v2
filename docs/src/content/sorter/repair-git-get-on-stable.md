---
layout: default
title: Repair git and get on stable
type: how-to
section: sorter
slug: sorter-repair-git-get-on-stable
kicker: SorterOS — Operations
lede: Put the machine's software back on a release from the Orange Pi's terminal, whatever state it is in.
permalink: /sorter/repair-git-get-on-stable/
---

For when **Settings → Versions** can't update the machine: it offers no update, the update fails, or someone changed the software by hand.

## Run the script

Log in to the Orange Pi (over SSH: user `root`, password `orangepi`) and run:

```bash
curl -fsSL https://raw.githubusercontent.com/basicallysource/sorter-v2/main/software/scripts/get-on-release.sh | sudo bash
```

That puts it on the newest stable release. For canary:

```bash
curl -fsSL https://raw.githubusercontent.com/basicallysource/sorter-v2/main/software/scripts/get-on-release.sh | sudo bash -s canary
```

It takes a few minutes and restarts the backend, so stop the machine first. It:

- leaves your settings, database, pictures and logs alone
- saves any edits to the software on a `backup/<date>` git branch
- fixes what stops an update: a branch, a stopped merge, a stale lock, damaged git files

## By hand

The same main steps, on a checkout in good shape:

1. Download the releases and put local edits aside.
   ```bash
   cd /home/orangepi/sorter-v2
   git fetch --tags --prune --prune-tags --force origin
   git -c user.name=sorter -c user.email=sorter@localhost stash
   ```
2. Check out the newest stable release (put `canary` in place of `stable` for canary).
   ```bash
   git checkout -f --detach "$(git tag -l 'sorter/stable/v*' --sort=-v:refname | head -1)"
   ```
3. Install the Python packages and build the UI.
   ```bash
   (cd software/sorter/backend && uv sync --locked)
   (cd software/sorter/frontend && CI=true pnpm install --frozen-lockfile && pnpm build)
   ```
4. Restart the backend.
   ```bash
   systemctl restart sorter-backend-dev.service
   ```
