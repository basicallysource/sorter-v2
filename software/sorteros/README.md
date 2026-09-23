# SorterOS

The Orange Pi image for the Sorter. It answers at `http://sorter.local`.

Getting it online, at every boot: Ethernet if there's a cable; else the Wi-Fi
saved on it (from the setup site before flashing, or from its setup page
earlier); else it broadcasts a `SorterOS-Setup-XXXXXX` network whose page
takes Wi-Fi details from a phone. See `build/overlay/usr/local/sbin/sorteros-network.py`.

## What's here

- **`build/`** — the image builder (Linux, arm64 or x86_64). See its README.
- **`portal/`** — Captive-portal stack the image boots into when no Wi-Fi is configured. FastAPI backend + SvelteKit static frontend, both source-of-truth here. The build copies them into `/usr/local/sbin/sorteros-portal.py` and `/var/www/portal/` on the image.
- **`test/`** — checks a built image, boots it in QEMU through first boot, and unit-tests the network decisions (`test_network.py`), before anyone flashes a card.
- **`sorteros-setup/`** — the setup site: writes Wi-Fi, hostname, SSH key and Tailscale key into a downloaded `.img` before flashing.

## Boot story

```
fresh flash
   │
   ├─→ sorteros-network.service (every boot, Before=firstboot)
   │    ├─ Wi-Fi in /etc/sorteros-config.toml (setup site)? save it in NM, once
   │    ├─ online within 45 s (90 s with a saved Wi-Fi)? → exit 0
   │    └─ else: SorterOS-Setup-XXXXXX + sorteros-portal on 10.42.0.1:80
   │         until the page joins a network, a cable appears, or a saved
   │         network comes back (retried every 3 min while nobody's on it);
   │         a failed join from the page brings the setup network back
   │
   ├─→ sorteros-firstboot.service (Type=simple, 60s loop)
   │    ├─ applies /etc/sorteros-config.toml whenever it changes
   │    │   (hostname, SSH key, Tailscale key)
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

Recovery is automatic: a machine that can't get online at boot (new router, changed password) opens its setup network.

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
└── sorteros-setup/    # the setup site (setup.basically.website)
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
