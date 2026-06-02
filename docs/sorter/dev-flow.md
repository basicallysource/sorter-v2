---
layout: default
title: Dev flow
type: how-to
section: sorter
slug: sorter-dev-flow
audience: self-hosting operator
last_verified: 2026-06-02
kicker: Sorter — Under the hood
lede: The two systemd services that run the machine in dev mode, how to enable them, and the difference between a soft restart and a full restart.
permalink: /sorter/dev-flow/
---

The machine runs as two systemd services: the **Python backend** (hardware,
vision, state) and the **SvelteKit UI** (the web interface you operate it
from). Each ships in a **dev** and a **prod** variant; everyone working on the
machine right now runs the **dev** ones, so those are the only ones this page
covers.

| Component | Dev service |
|---|---|
| Backend | `sorter-backend-dev.service` |
| UI | `sorter-ui-dev.service` |

The dev services run the UI through Vite with hot-module reload, so a code
change to a `.svelte` or `.ts` file shows up in the browser within a second
without a manual restart.

## Enabling the dev services

"Enabling" a systemd service does two separate things:

- **`enable`** marks the service to start automatically on every boot.
- **`start`** starts it right now, this boot.

`systemctl enable --now` does both at once:

```bash
sudo systemctl enable --now sorter-backend-dev.service sorter-ui-dev.service
```

Check what is currently running and watch the logs with:

```bash
systemctl status sorter-backend-dev.service sorter-ui-dev.service
journalctl -u sorter-backend-dev.service -f
journalctl -u sorter-ui-dev.service -f
```

## Restarting the backend

When you change backend Python code, the running process needs to pick it up.
There are two ways to do that, and they are not the same thing.

### Soft restart (the fast one)

A soft restart bounces only the backend's `main.py` worker, leaving its
supervisor process and the systemd unit untouched. The supervisor kills the
worker and immediately launches a fresh one — a clean Python interpreter with
every module re-imported from disk. It re-initializes the hardware from
scratch and is back online in about two seconds.

This is what you want for essentially every code edit. Trigger it by POSTing to
the supervisor's control endpoint:

```bash
curl -sS -X POST http://127.0.0.1:8001/api/supervisor/restart \
  -H "Origin: http://sorter.local:5173"
```

The `Origin` header is required — the supervisor only accepts requests from an
allowed UI origin. `http://sorter.local:5173` works from any machine.

> **Tip — make it a one-word command.** Add a shell alias on the machine so a
> soft restart is just `soft-reboot`:
>
> ```bash
> echo "alias soft-reboot='curl -sS -X POST http://127.0.0.1:8001/api/supervisor/restart -H \"Origin: http://sorter.local:5173\"'" >> ~/.bashrc && source ~/.bashrc
> ```

> The **Restart Backend** button in the machine UI (under the power menu in the
> top-right header) does exactly this — it is the same soft restart as the
> `curl` call above, just from the browser. It releases the camera handles,
> bounces `main.py` through the supervisor, then reconnects the UI
> automatically.

### Full restart (the heavier one)

A full restart goes through systemd and bounces the **whole service** — the
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
| `machine.toml` | Soft restart (UI button or `curl`) |
| The `.env` file or a newly installed package | Full restart (`systemctl restart`) |
| The systemd unit file | Full restart (`systemctl restart`) |

For the UI, Vite hot-reloads source edits on its own; you only need
`systemctl restart sorter-ui-dev.service` if the Vite process itself wedges or
its unit/environment changed.
