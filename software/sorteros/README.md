# SorterOS

The Orange Pi image for the Sorter. One generic image: plug in Ethernet and it
sets itself up, or it opens a Wi-Fi hotspot with a setup page when there's no
cable. It answers at `http://sorter.local`.

> SorterOS v3 (`sorteros/v3.x` tags) instead baked Wi-Fi settings into the
> `.img` before flashing, with the browser customizer in `sorteros-setup/`
> (setup.basically.website). That site only works on v3 images.

## What's here

- **`build/`** — the image builder (Linux, arm64 or x86_64). See its README.
- **`portal/`** — Captive-portal stack the image boots into when no Wi-Fi is configured. FastAPI backend + SvelteKit static frontend, both source-of-truth here. The build copies them into `/usr/local/sbin/sorteros-portal.py` and `/var/www/portal/` on the image.
- **`test/`** — boots a built image in QEMU and checks first boot end to end, before anyone flashes a card.
- **`sorteros-setup/`** — the v3 customizer site.

## Boot story

```
fresh flash
   │
   ├─→ sorteros-onboarding.service (Before=firstboot)
   │    ├─ /var/lib/sorteros/wifi-configured present? → exit 0
   │    ├─ default route within 45 s (Ethernet)? → exit 0
   │    └─ else: nmcli AP up + sorteros-portal on 10.42.0.1:80
   │              └─ user submits SSID/password
   │                    └─ portal writes .nmconnection, touches gate,
   │                       brings the AP down
   │
   ├─→ sorteros-firstboot.service (Type=simple, 60s loop)
   │    ├─ reads /etc/sorteros-config.toml (populated by portal)
   │    ├─ stages: ssh-keys, grow-rootfs, swap, clone-repo (newest
   │    │           sorter/stable/v* tag), env files, machine.toml,
   │    │           uv-sync, pnpm, install-services
   │    ├─ status HTML on :80 until those are done, with any stage's error
   │    └─ then tailscale (if a key was given) in the background; gives up
   │       after 10 failures instead of blocking anything
   │
   └─→ sorter-ui.service takes over :80 with the regular setup wizard,
       and the backend installs Hive's default vision model for this
       hardware on every channel that has none
```

The image does not carry the Sorter software: first boot checks out the newest
`sorter/stable/v*` tag, the same release channel the UI's Versions page
updates within. `build.py --ref <branch>` bakes a different ref for a test
image.

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
├── test/              # QEMU boot test
└── sorteros-setup/    # v3 image customizer (setup.basically.website)
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
