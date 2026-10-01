---
layout: default
title: Install on Linux (generic)
type: installation
section: sorter
slug: sorter-installation-linux-generic
kicker: Installation — Linux
lede: How to take a fresh Linux box from clean install to a running SorterOS UI in your browser. One script, two flags, then the in-app Setup Wizard takes over.
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
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
./install.sh
```

That's it. The installer is idempotent — re-running it on a partially-installed machine just confirms the steps it can skip.

What `install.sh` actually does, in order:

<ol class="numbered-steps">
  <li><strong><code>apt install</code></strong> the system packages: <code>git</code>, <code>curl</code>, <code>build-essential</code>, <code>libgl1</code>, <code>libglib2.0-0</code>, <code>lsof</code>, <code>v4l-utils</code>. <code>libgl1</code> is what OpenCV needs at import time.</li>
  <li><strong>Install a udev rule</strong> for Raspberry Pi Pico boards (<code>/etc/udev/rules.d/99-sorter-pico.rules</code>), so Pico USB access belongs to the <code>plugdev</code> group plus the active desktop seat user. The installer adds your user to <code>plugdev</code>; a headless or SSH session needs a logout and login before that takes effect.</li>
  <li><strong>Install <code>uv</code></strong>, the Python toolchain, if it is not already on the box. <code>uv</code> then fetches the exact Python version the project pins, so you do not need <code>apt python3</code>.</li>
  <li><strong>Install Node.js 20.x and <code>pnpm</code></strong> via NodeSource. <code>pnpm</code> is what the dev runner invokes, so <code>npm</code> and <code>yarn</code> do not substitute.</li>
  <li><strong>Write <code>software/.env</code></strong> if there is not one already.</li>
  <li><strong>Copy <code>machine.example.toml</code> to <code>software/machine.toml</code></strong> if there is not one already. That copy is the machine's own config, and settings you save in the UI are written to it. The example itself is never used directly, so a setting you save never lands in a file git tracks.</li>
  <li><strong><code>uv sync</code></strong> in <code>software/sorter/backend/</code>. This is the slow step on a first install, because uv downloads the Python interpreter and resolves the backend dependencies, OpenCV and ONNX Runtime among them.</li>
  <li><strong><code>pnpm install --frozen-lockfile</code></strong> in <code>software/sorter/frontend/</code>, which resolves the UI toolchain.</li>
</ol>

An existing `.env` or `machine.toml` is left alone, which is what makes a re-run safe.

## Verify the install

When the installer finishes you can start the dev runner:

```bash
./dev.sh
```

`./dev.sh` starts the Python backend on `:8000` and the Vite dev server on `:5173`, prefixes both log streams, and restarts either one if it crashes. Stop with Ctrl-C.

Then open `http://localhost:5173/` (or `http://<machine-ip>:5173/` from another device on the same network). You should see the SorterOS UI.

If the UI does not come up, see [SorterOS troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}).

## The finished result

The SorterOS UI open in a browser, with nothing set up on the machine yet.

<div class="img-placeholder">Screenshot of the SorterOS UI as it first loads on a generic Linux install, before the setup wizard has been run.</div>

## Next

**Flash the control board before you open the setup wizard.** The wizard only lists boards that already answer on USB serial, so a board with no firmware on it does not appear and the wizard says `No MCU buses found`. [Software setup]({{ '/hardware/software-setup/' | relative_url }}) step 2 has the route.

Then [First setup in the UI]({{ '/sorter/first-setup/' | relative_url }}) takes the setup wizard step by step.

## Installer flags

```bash
./install.sh --help
./install.sh                 # default — install everything in dev mode
./install.sh --as-service    # also build the UI and run the Sorter as a systemd service
./install.sh --skip-apt      # skip the apt step (useful when packages are already installed)
```

### Running as a systemd service

For an "appliance" install on the Pi 5 that should boot straight into a running SorterOS without anyone touching `./dev.sh`:

```bash
./install.sh --as-service
```

In addition to all the steps above, this also:

- runs `pnpm build`, which writes the UI as static files to `software/sorter/frontend/build/`;
- substitutes the actual user, paths, and binary locations into the unit templates under `software/systemd/`;
- writes two units into `/etc/systemd/system/`: `sorter-backend.service` and its `-dev` variant;
- runs `systemctl daemon-reload`, then `systemctl enable --now sorter-backend-dev.service`, so it starts immediately and on every subsequent boot.

**It is the `-dev` unit that gets enabled.** The two differ only in how quickly systemd restarts them; enable `sorter-backend.service` instead if you prefer.

**The backend's supervisor serves the UI on port 80**, so a service install answers at `http://<machine name>/` with no port on the end. It serves the build, so there is no Node process running on the machine, and the page still loads while the backend itself restarts. The `:5173` address is the dev runner's, and only applies when you start `./dev.sh` by hand. After changing UI code, run `pnpm build` in `software/sorter/frontend/` again; the next page load picks it up.

View the logs with:

```bash
sudo journalctl -u sorter-backend-dev -f
```

## Verifying the installer in Docker

The whole install path is reproducibly tested against a fresh Debian 12 container so we catch regressions before they hit a real machine. From the repo root:

```bash
software/scripts/test_install_in_docker.sh
```

This script:

<ol class="numbered-steps">
  <li>builds a minimal <code>debian:12-slim</code> image whose only pre-installed packages are <code>sudo</code>, <code>curl</code>, <code>ca-certificates</code> and <code>git</code>, so everything else has to come from <code>install.sh</code> itself;</li>
  <li>copies the working tree into the container, strips any host-side dev state (<code>.env</code>, <code>.venv</code>, <code>node_modules</code>), and runs <code>./install.sh</code>;</li>
  <li>smoke-tests the backend by importing the trickiest Python dependencies (<code>fastapi</code>, <code>cv2</code>, <code>onnxruntime</code>, <code>uvicorn</code>, <code>numpy</code>) inside the freshly built <code>uv</code> environment;</li>
  <li>runs <code>pnpm exec vite --version</code> to confirm the UI toolchain is callable;</li>
  <li>runs <code>systemd-analyze verify</code> against the unit files to catch syntax regressions.</li>
</ol>

What the Docker test deliberately does **not** cover: USB serial discovery of Pico boards, camera enumeration, Hailo / RKNN runtimes, anything else that needs physical hardware. Those are exercised on real devices, not in CI.
