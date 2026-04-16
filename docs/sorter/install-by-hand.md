---
layout: default
title: Install the Sorter by hand
type: how-to
slug: sorter-install-by-hand
kicker: Sorter — Setup
lede: The manual install sequence — for when `install.sh` does not yet support your platform, or when you want to know exactly what the installer is doing on yours.
permalink: /sorter/install-by-hand/
---

## When to use this

Use this guide when:

- you are installing on a system the [one-command installer]({{ '/sorter/installation/' | relative_url }}) does not yet support;
- you want to walk every step yourself to understand what the installer is doing;
- you are debugging a failing `install.sh` and want to isolate which step is going wrong.

If neither of those applies, use the [one-command installer]({{ '/sorter/installation/' | relative_url }}) instead — it is the maintained path and the one we test against in CI.

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
  git git-lfs curl ca-certificates \
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
git lfs install
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
git lfs pull
```

`git lfs pull` is what brings down the detector model artifacts and the parts catalogue.

### 6. Generate `.env`

```bash
cp .env.example .env
$EDITOR .env
cp ui/.env.example ui/.env
```

This is the step that bites people manually: `.env.example` ships with placeholder paths like `/home/user/sorter-v2/...` which you must replace with the absolute path of your actual clone. The one-command installer does this automatically — by hand you have to.

### 7. Install dependencies

```bash
( cd client && uv sync )
( cd ui && pnpm install )
```

`uv sync` is the slow step on first install because it downloads the Python interpreter and resolves all 53 backend dependencies including OpenCV and ONNX Runtime.

### 8. Start the dev runner

```bash
./dev.sh
```

This starts the Python backend on `:8000` and the Vite dev server on `:5173`.

## Verify the install

Open `http://localhost:5173/` in a browser. You should see the Sorter UI. The first time you open it, the in-app **Setup Wizard** takes over.

```bash
curl -fsS http://localhost:8000/api/health
```

Should return a JSON status response.

## If something goes wrong

See [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) for the common failures and their fixes.

## Related

- [Install the Sorter on a Linux machine]({{ '/sorter/installation/' | relative_url }}) — the maintained one-command path.
- [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }})
