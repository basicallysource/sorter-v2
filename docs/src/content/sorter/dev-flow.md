---
layout: default
title: Dev flow
type: how-to
section: sorter
slug: sorter-dev-flow
audience: self-hosting operator
last_verified: 2026-06-02
kicker: SorterOS — Under the hood
lede: The systemd service that runs the machine in dev mode, how to enable it, and the difference between a soft restart and a full restart.
permalink: /sorter/dev-flow/
---

The machine runs as one systemd service: the **Python backend** (hardware,
vision, state). Its supervisor, the small process that keeps the backend
running, also serves the **UI** (the web interface you operate it from) on port
80, from the UI's static build in `software/sorter/frontend/build/`. The
service ships in a **dev** and a **prod** variant; everyone working on the
machine right now runs the **dev** one, `sorter-backend-dev.service`, so that
is the only one this page covers.

## Enabling the dev service

"Enabling" a systemd service does two separate things:

- **`enable`** marks the service to start automatically on every boot.
- **`start`** starts it right now, this boot.

`systemctl enable --now` does both at once:

```bash
sudo systemctl enable --now sorter-backend-dev.service
```

Check what is currently running and watch the logs with:

```bash
systemctl status sorter-backend-dev.service
journalctl -u sorter-backend-dev.service -f
```

## Restarting the backend

When you change backend Python code, the running process needs to pick it up.
There are two ways to do that, and they are not the same thing.

### Soft restart (the fast one)

A soft restart bounces only the backend's `main.py` worker, leaving its
supervisor process and the systemd unit untouched. The supervisor stops the
worker and immediately launches a fresh one: a clean Python interpreter with
every module re-imported from disk. It re-initializes the hardware from
scratch and is back online in about two seconds.

This is what you want for essentially every code edit. Trigger it by POSTing to
the supervisor, on the machine's port 80:

```bash
curl -sS -X POST http://sorter.local/api/supervisor/restart \
  -H "Origin: http://sorter.local"
```

The `Origin` header is required and must name the address the request goes
to, as a browser's does from the UI this supervisor served. That keeps pages
from other sites from restarting the machine.

> The **Restart Backend** button in the machine UI (under the power menu in the
> top-right header) does exactly this: it is the same soft restart as the
> `curl` call above, just from the browser. It bounces `main.py` through the
> supervisor, then reconnects the UI automatically. It works even when the
> backend has stopped answering, because the supervisor answers instead.

### Full restart (the heavier one)

A full restart goes through systemd and bounces the **whole service**: the
supervisor process and its `main.py` worker together:

```bash
sudo systemctl restart sorter-backend-dev.service
```

This re-reads the systemd unit and re-sources the environment file, so it is
the one to use when something *outside* the Python worker changed: the systemd
unit itself, the `.env` file, or a newly installed package in the environment.
It is a few seconds slower than a soft restart because systemd waits out its
configured `RestartSec` delay before bringing the service back.

| You changed… | Use |
|---|---|
| A `.py` file in the backend | Soft restart (UI button or `curl`) |
| The `.env` file or a newly installed package | Full restart (`systemctl restart`) |
| The systemd unit file | Full restart (`systemctl restart`) |
| UI code | `pnpm build` in `software/sorter/frontend/`, then reload the page |

## Working on the UI

The supervisor serves whatever is in `software/sorter/frontend/build/`, so a
rebuild shows on the next page load with no restart. For hot reload while you
work, run the Vite dev server instead and open port 5173:

```bash
cd software/sorter/frontend
pnpm dev --host
```

It talks to the same backend on port 8000.
