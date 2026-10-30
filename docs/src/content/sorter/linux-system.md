---
layout: default
title: The Linux system
type: reference
section: sorter
slug: sorter-linux-system
audience: self-hosting operator
applies_to: sorteros v4.x
last_verified: 2026-10-25
kicker: SorterOS - Under the hood
lede: What the SorterOS image changes compared to the Orange Pi Ubuntu image it is built on, the system software that matters, and where the Sorter software and its configuration live on the machine.
permalink: /sorter/linux-system/
---

SorterOS is not a new Linux distribution. It is the Orange Pi vendor image
(Ubuntu 22.04 "Jammy", server edition, kernel 6.1.99) with a small set of
changes on top. The Sorter software itself is **not** in the image: the machine
downloads it on first boot. This page lists what is different, so you know what
you can touch over SSH and what a reflash resets.

## What is different from the base image

The image is built by `software/sorteros/build/` in the
[sorter-v2 repository](https://github.com/basicallysource/sorter-v2). The base
image is pinned by checksum, and the build:

- **Adds a short list of packages** (below), plus Node 22, `pnpm`, `uv` and the
  Python packages the setup page needs. Nothing else is installed or upgraded:
  the build does not run a general `apt upgrade`.
- **Adds two services** that run on every boot: `sorteros-network` (gets the
  machine online, or opens a setup Wi-Fi network) and `sorteros-firstboot`
  (installs the Sorter software, then keeps applying your settings).
- **Adds a udev rule** so the control boards (Raspberry Pi Picos) can be opened
  by the backend.
- **Makes the card more crash-tolerant**, because machines get their power cut:
  the root filesystem is mounted with `errors=panic` and the kernel is told
  `fsck.repair=yes panic=10`, so a filesystem error reboots the machine and the
  next boot repairs it instead of the disk silently going read-only.
- **Sets the hostname** to `sorter` (answering as `sorter.local`), a login
  banner, and an `ll` alias.
- **Makes the disk bigger**: the image is grown by 4 GiB at build time, and on
  first boot the root partition is expanded to fill the whole card.
- **Changes network behaviour**: the "is the internet really there" check used
  by NetworkManager is set to a 60 second interval, and `dnsmasq` as a
  stand-alone service is masked (NetworkManager runs its own copy for the setup
  network).

Things that are **not** changed: the kernel and vendor drivers (so the Wi-Fi
module and the board's hardware support come from the Orange Pi image), the
`orangepi` user, and the default SSH credentials in
[Install the SorterOS image]({{ '/sorter/installation/sorter-os/' | relative_url }}).

## The system software that matters

| Software | What it does here |
|----------|-------------------|
| **systemd** | Starts and restarts everything. The Sorter backend, first-boot and network setup are all systemd services, and their output goes to the journal. |
| **NetworkManager** (+ `dnsmasq-base`) | Ethernet and Wi-Fi, and the `SorterOS-Setup-XXXXXX` access point. Everything under Settings → Networking in the UI drives it. |
| **avahi-daemon** + `libnss-mdns` | Makes the machine answer at `sorter.local` and lets it resolve other `.local` names. |
| **systemd-timesyncd** | Keeps the clock right. The Orange Pi has no battery clock, and without a correct time HTTPS fails with "certificate not yet valid". |
| **Python 3.12 via `uv`** | The backend runs in its own virtual environment made by `uv`. The system `python3` (3.10) is only used by the image's own services. |
| **Node 22 and `pnpm`** | Build the Sorter UI on first boot and on every update. The UI is served as static files; Node does not run while sorting. |
| **git** | The Sorter software is a git checkout. The Versions page in the UI switches between release tags with it. |
| **Tailscale** | Installed on first boot (so it has internet), and only joined to a network if you gave a key. See [Networking]({{ '/sorter/networking/' | relative_url }}). |
| **v4l-utils**, `libgl1`, `libglib2.0-0` | Camera inspection tools, and libraries OpenCV needs. |
| **cloud-guest-utils**, `qrencode`, `iw`, `figlet` | Growing the root partition, QR codes on the setup page, Wi-Fi inspection, the login banner. |

## Where the Sorter software is installed

On first boot the machine clones the repository and checks out the newest
`sorter/stable/v*` release tag. It lives at:

- **`/home/orangepi/sorter-v2`** is the git checkout. The software is in its
  `software/` directory.
- **`software/sorter/backend/`** is the Python backend and its virtual
  environment (`.venv`, made by `uv sync`).
- **`software/sorter/frontend/`** is the UI. Its `build/` directory is the
  compiled site the backend serves on port 80.

The repository is cloned without file contents for old commits, but with all
tags, so switching versions only downloads what that version needs. A
[test image]({{ '/sorter/dev-flow/' | relative_url }}) can be built to start on
a branch instead of the stable channel. If the checkout is damaged,
[Repair git and get on stable]({{ '/sorter/repair-git-get-on-stable/' | relative_url }})
puts it back.

### How it runs

The backend is one systemd service, defined by a unit file that first boot
copies from `software/systemd/` into `/etc/systemd/system/`:

- **`sorter-backend-dev.service`** is what SorterOS enables. It runs the
  supervisor (`supervisor.py`) with `uv run`, restarts it two seconds after any
  failure, and never gives up after repeated failures. The supervisor starts the
  backend, serves the UI on port 80, and handles soft and full restarts. See
  [Dev flow]({{ '/sorter/dev-flow/' | relative_url }}).
- **`sorter-backend.service`** is the same without the dev behaviour. The two
  conflict, so only one exists at a time. `systemctl list-units 'sorter*'` shows
  which one you have.

Both run as `root`, so the backend can use the USB, serial and network devices
without extra permissions. Python's bytecode cache is kept in `/tmp`, so a power
cut cannot leave a half-written `.pyc` that crashes the backend forever.

The backend's output goes to the systemd journal:
`journalctl -u sorter-backend-dev -f`. The image does not set up a persistent journal, so a reboot
clears it. The [Logs]({{ '/sorter/logs/' | relative_url }}) page in the UI shows
the backend's own log file instead.

## Where configuration is stored

There is no single settings database. Each kind of setting has its own place:

| What | Where |
|------|-------|
| Hardware and machine setup (cameras, servos, steppers, layout) | `/home/orangepi/sorter-v2/software/machine.toml`. Written by the UI, reference in [machine.toml reference]({{ '/sorter/machine-toml-reference/' | relative_url }}). |
| Environment variables for the backend (debug level, API host, `MACHINE_SPECIFIC_PARAMS_PATH`) | `/home/orangepi/sorter-v2/software/.env`, written once on first boot and read by the service. |
| Runtime state: polygons, calibrations, sync state, the Hive link, secrets | `software/sorter/backend/local_state.sqlite`. Secrets in it are encrypted with a key kept in the same file, so a copy of the file moves them to another machine only with it. |
| Sorting profiles | `software/sorter/backend/sorting_profiles/`, with the one in use in `active_sorting_profile.json`. |
| Uploaded BrickStore inventories | `software/sorter/backend/bsx_files/` |
| Downloaded vision models | `software/sorter/backend/blob/hive_detection_models/` |
| Wi-Fi, hostname, SSH key and Tailscale key from the setup site | `/etc/sorteros-config.toml`. First boot reads it again whenever it changes. |
| Saved Wi-Fi networks | NetworkManager's own store, `/etc/NetworkManager/system-connections/`. |
| Image version and software channel | `/etc/sorteros/version` and `/etc/sorteros/ref` |
| Which first-boot stages are done, and which software was checked out | `/var/lib/sorteros/` |
| Tailscale key and hostname override | `/etc/sorteros/tailscale.env` and `/etc/sorteros/tailscale_hostname_override` |

`machine.toml`, `.env`, `local_state.sqlite`, the sorting profiles and the
models are ignored by git, so switching versions or repairing the checkout
leaves them alone. A reflash
resets everything on this page. To keep a machine's setup, copy `machine.toml`
and `local_state.sqlite` off it first.

### What first boot does

First boot runs these stages in order, each marked done when it succeeds, and
retries the ones that failed. The progress page at `http://sorter.local` shows
them:

1. Make the SSH host keys.
2. Grow the root partition to fill the card.
3. Create an 8 GB swap file at `/swapfile`.
4. Clone the repository and check out the release.
5. Write `.env` and a minimal `machine.toml`, only if they do not exist.
6. Install the backend's Python packages (`uv sync`) and the UI's (`pnpm install`),
   then build the UI.
7. Install and start the backend service.
8. Install Tailscale and join, if a key was given.

Because every stage is checked before it runs, a machine that is already set up
does nothing here beyond applying changed settings from
`/etc/sorteros-config.toml`.
