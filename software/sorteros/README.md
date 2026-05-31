# SorterOS v4

> Predecessor: SorterOS v3 used a browser-side image customizer
> (`sorteros-setup/`) that patched WiFi/hostname/SSH placeholders into a
> downloaded `.img` before flashing. v4 ships a single generic image and
> moves all configuration to a captive portal on the device — no more
> placeholders, no more pre-flash customizer.

## What's here

- **`build/`** — Python image builder. Runs locally on the M2 Mac via colima. No qemu, no Hive. Target wall-time < 3 min.
- **`portal/`** — Captive-portal stack the image boots into when no Wi-Fi is configured. FastAPI backend + SvelteKit static frontend, both source-of-truth here. The build copies them into `/usr/local/sbin/sorteros-portal.py` and `/var/www/portal/` on the image.
- **`build-dashboard/`** — Local web UI + agent API in front of the builder.

## Boot story

```
fresh flash
   │
   ├─→ sorteros-onboarding.service (Before=firstboot)
   │    ├─ /var/lib/sorteros/wifi-configured present? → exit 0
   │    └─ else: nmcli AP up + sorteros-portal on 10.42.0.1:80
   │              └─ user submits SSID/password
   │                    └─ portal writes .nmconnection, touches gate,
   │                       brings the AP down
   │
   ├─→ sorteros-firstboot.service (Type=simple, 60s loop)
   │    ├─ reads /etc/sorteros-config.toml (populated by portal)
   │    ├─ stages: ssh-keys, grow-rootfs, swap, repo-clone, lfs-pull,
   │    │           env files, machine.toml, tailscale-up, …
   │    └─ status HTML on :80 until done
   │
   └─→ sorter-ui.service takes over :80 with the regular setup wizard
```

Recovery: deleting `/var/lib/sorteros/wifi-configured` (and rebooting) drops the device back into AP mode. A future change wires this to a long-press GPIO button.

## Layout

```
sorteros/
├── README.md          # this file
├── build/             # image builder (build.py + overlay + chroot_apt.sh)
├── portal/            # captive-portal source (backend + frontend)
│   ├── backend/portal.py
│   ├── frontend/      # SvelteKit + adapter-static + Tailwind v4
│   └── README.md      # local dev / mock-mode walkthrough
└── build-dashboard/   # local builder UI
```

The portal source is the single source of truth — the build's `portal` phase copies `portal/backend/portal.py` into the rootfs and `pnpm build`s `portal/frontend/` into `/var/www/portal/`. Editing the portal during development uses mock mode and never touches an image.

## Versioning

Version lives in `build/config.toml` under `[output] version`. It flows into the output filename (`sorteros-v{version}-{date}.img`). Bump before every build that will be flashed to hardware.

| Change type | Bump | Examples |
|---|---|---|
| New feature, new firstboot stage, new overlay file | **minor** (4.0 → 4.1) | adding `stage_clone_repo`, new portal flow step |
| Bug fix, config tweak, comment-only change | **patch** (4.0 → 4.0.1) | fixing `sh()` error swallowing |
| Incompatible firstboot protocol change, partition layout change | **major** (4.x → 5.0) | changing the config-toml schema, switching base image |

Always bump before starting a build — never retroactively rename a build that was already flashed to hardware.
