---
layout: default
title: Install on Linux (generic)
type: installation
section: sorter
slug: sorter-installation-linux-generic
kicker: Installation — Linux
lede: How to take a fresh Linux box from clean install to a running Sorter UI in your browser. One script, two flags, then the in-app Setup Wizard takes over.
permalink: /sorter/installation/linux-generic/
audience: self-hosting operator
applies_to: sorter 2.x
last_verified: 2026-05-19
---

## Supported platforms

The installer is written against a freshly installed **Debian 12** or **Ubuntu 24.04** system (`amd64` or `aarch64`). It also works on **Raspberry Pi OS Bookworm** on a Pi 5, which is the canonical target.

## Prerequisites

- a sudo-capable user account
- a working internet connection
- ~3 GB free disk (Python interpreter, `node_modules`, model artifacts)

## The one-command install

```bash
git lfs install
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
./install.sh
```

That's it. The installer is idempotent — re-running it on a partially-installed machine just confirms the steps it can skip.

What `install.sh` actually does, in order:

1. **`apt install`** the system packages — `git`, `git-lfs`, `curl`, `build-essential`, `libgl1`, `libglib2.0-0`, `lsof`, `v4l-utils`. `libgl1` is what OpenCV needs at import time; the rest are dependencies of the toolchain or the dev runner.
2. **Install a udev rule** for Raspberry Pi Pico boards (`/etc/udev/rules.d/99-sorter-pico.rules`). This restricts Pico access to the `plugdev` group plus the active desktop seat user (via `uaccess`), preventing arbitrary local users from flashing firmware. The installer adds your user to `plugdev`; headless/SSH sessions need a logout/login cycle, but the seat user's desktop session works immediately.
3. **Install `uv`** (the Python toolchain) if it isn't already on the box. `uv` then fetches the exact Python version pinned by the project — no `apt python3` needed.
4. **Install Node.js 20.x and `pnpm`** via NodeSource. `pnpm` is mandatory here, not `npm`: the dev runner explicitly invokes `pnpm dev`.
5. **`git lfs pull`** the detector model artifacts and the parts catalogue (skip with `--skip-lfs`).
6. **Generate `.env`** with the *correct* absolute paths discovered from the install location. No more editing `/home/user/sorter-v2/...` placeholders by hand. (The UI's own `.env` is also seeded from its example.)
7. **`uv sync`** in `software/sorter/backend/` — this is the slow step on first install because uv downloads the Python interpreter and resolves all 53 backend dependencies including OpenCV and ONNX Runtime.
8. **`pnpm install --frozen-lockfile`** in `software/sorter/frontend/` — resolves the SvelteKit + Vite + Tailwind toolchain and the in-app component set.

## Verify the install

When the installer finishes you can start the dev runner:

```bash
./dev.sh
```

`./dev.sh` starts the Python backend on `:8000` and the Vite dev server on `:5173`, prefixes both log streams, and restarts either one if it crashes. Stop with Ctrl-C.

Then open `http://localhost:5173/` (or `http://<machine-ip>:5173/` from another device on the same network). You should see the Sorter UI. The first time you open it, the in-app **Setup Wizard** will take over.

If the UI does not come up, see [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}).

## Installer flags

```bash
./install.sh --help
./install.sh                 # default — install everything in dev mode
./install.sh --as-service    # also build the UI for production and install systemd units
./install.sh --skip-lfs      # skip git lfs pull (useful in CI / Docker / when LFS already pulled)
./install.sh --skip-apt      # skip the apt step (useful when packages are already installed)
```

### Running as a systemd service

For an "appliance" install on the Pi 5 that should boot straight into a running Sorter without anyone touching `./dev.sh`:

```bash
./install.sh --as-service
```

In addition to all the steps above, this also:

- runs `pnpm build` to produce a production UI bundle under `software/sorter/frontend/build/`;
- substitutes the actual user, paths, and binary locations into the unit templates under `software/systemd/`;
- writes `lego-sorter-backend.service` and `lego-sorter-ui.service` into `/etc/systemd/system/`;
- runs `systemctl daemon-reload && systemctl enable --now …` so both services start immediately and on every subsequent boot.

The two services are independent on purpose — you can `systemctl restart lego-sorter-backend` while iterating on the Python side without bouncing the UI, and vice versa. View the logs with:

```bash
sudo journalctl -u lego-sorter-backend -f
sudo journalctl -u lego-sorter-ui -f
```

## Verifying the installer in Docker

The whole install path is reproducibly tested against a fresh Debian 12 container so we catch regressions before they hit a real machine. From the repo root:

```bash
software/scripts/test_install_in_docker.sh
```

This script:

1. builds a minimal `debian:12-slim` image whose only pre-installed packages are `sudo`, `curl`, `ca-certificates`, and `git` — everything else has to come from `install.sh` itself;
2. copies the working tree into the container, strips any host-side dev state (`.env`, `.venv`, `node_modules`), and runs `./install.sh --skip-lfs`;
3. smoke-tests the backend by importing the trickiest Python deps (`fastapi`, `cv2`, `onnxruntime`, `uvicorn`, `numpy`) inside the freshly-built `uv` environment;
4. runs `pnpm exec vite --version` to confirm the UI toolchain is callable;
5. runs `systemd-analyze verify` against both unit files to catch unit-syntax regressions.

What the Docker test deliberately does **not** cover: USB serial discovery of Pico boards, camera enumeration, Hailo / RKNN runtimes, anything else that needs physical hardware. Those are exercised on real devices, not in CI.
