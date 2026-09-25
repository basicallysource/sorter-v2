---
layout: default
title: Install by hand
type: how-to
section: sorter
slug: installation-by-hand
kicker: Installation — Manual
lede: The manual install sequence — for when the one-command installer does not yet support your platform, or when you want to know exactly what it does.
permalink: /sorter/installation/by-hand/
audience: self-hosting operator
applies_to: sorter 2.x
last_verified: 2026-04-08
---

## When to use this

Use this guide when:

- you are installing on a system the [one-command installer]({{ '/sorter/installation/linux-generic/' | relative_url }}) does not yet support;
- you want to walk every step yourself to understand what the installer is doing;
- you are debugging a failing `install.sh` and want to isolate which step is going wrong.

If neither of those applies, use the [one-command installer]({{ '/sorter/installation/linux-generic/' | relative_url }}) instead — it is the maintained path and the one we test against in CI.

## Prerequisites

You will need:

- a sudo-capable user account
- a working internet connection
- ~3 GB free disk
- a shell that understands `curl | bash` patterns (any modern bash or zsh)

## Manual install sequence

### 1. System packages

```bash
sudo apt update && sudo apt install -y \
  git curl ca-certificates \
  build-essential pkg-config \
  libgl1 libglib2.0-0 lsof v4l-utils
```

`libgl1` is what OpenCV needs at import time — leaving it out is the most common silent backend failure.

### 2. Udev rule for Pico boards

This restricts Pico USB serial access to the `plugdev` group plus the active desktop seat user (via `uaccess`), so arbitrary local users cannot flash firmware. Add your user to `plugdev` for headless/SSH access; a desktop seat session works immediately without logout/login.

```bash
sudo cp software/systemd/99-sorter-pico.rules /etc/udev/rules.d/
sudo usermod -aG plugdev "$USER"   # log out/in for headless/SSH sessions
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 3. `uv` (Python toolchain)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

`uv` will fetch the exact pinned Python version when you run `uv sync` later — you do not need to install Python from apt.

### 4. Node 20 and pnpm (UI toolchain)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pnpm
```

`pnpm` is mandatory — the dev runner explicitly invokes `pnpm dev`. Do not use `npm` or `yarn`.

### 5. Clone the repo

```bash
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
```

Every path from here is relative to `software/`.

Vision models are not in the repo: once the backend is running it downloads Hive's default detection model for this computer and puts it on every channel.

### 6. Config files

From `software/`:

```bash
cp .env.example .env
$EDITOR .env
cp machine.example.toml machine.toml
```

This is the step that bites people manually: `.env.example` ships with a placeholder path, `SORTING_PROFILE_PATH="/home/user/sorter-v2/software/..."`, which you must replace with the absolute path of your own clone.

`machine.toml` is the machine's own config, and settings you save in the UI are written to it. Copy it rather than pointing the Sorter at the example, or those settings land in a file git tracks. The [machine.toml reference]({{ '/sorter/machine-toml-reference/' | relative_url }}) describes every field, and the setup wizard fills most of them in for you.

### 7. Install dependencies

```bash
( cd sorter/backend && uv sync )
( cd sorter/frontend && pnpm install --frozen-lockfile )
```

`uv sync` is the slow step on first install because it downloads the Python interpreter and resolves the backend dependencies, OpenCV and ONNX Runtime among them.

### 8. Start the dev runner

```bash
./dev.sh
```

This starts the Python backend on `:8000` and the Vite dev server on `:5173`.

## Verify the install

Open `http://localhost:5173/` in a browser. You should see the Sorter UI.

```bash
curl -fsS http://localhost:8000/api/health
```

Should return a JSON status response.

## If something goes wrong

See [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) for the common failures and their fixes.

## The finished result

The Sorter UI open in a browser, with nothing set up on the machine yet.

<div class="img-placeholder">Screenshot of the Sorter UI as it first loads on a by-hand install, before the setup wizard has been run.</div>

## Next

**Flash the control board before you open the setup wizard.** The wizard only lists boards that already answer on USB serial, so a board with no firmware on it does not appear and the wizard says `No MCU buses found`. [Software setup]({{ '/hardware/software-setup/' | relative_url }}) step 2 has the route.

Then [First setup in the UI]({{ '/sorter/first-setup/' | relative_url }}) takes the setup wizard step by step.

## Related

- [Install on a Linux machine (generic)]({{ '/sorter/installation/linux-generic/' | relative_url }}) — the maintained one-command path.
- [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }})
