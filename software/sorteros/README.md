# SorterOS v3

> Full design doc: `sorter-v2-agent-notes/orange_pi/sorteros_v3.md`.
> Read it before touching anything here.

## What's here

- **`build/`** — Python builder. Runs locally on the M2 Mac via colima. No qemu, no Hive. Target wall-time < 3 min.
- **`sorteros-setup/`** — Pure-browser .img customizer. SvelteKit + Tailwind, deployed to Vercel at <https://setup.basically.website>. User uploads an image, fills out a form (Wi-Fi, hostname, SSH keys), downloads a customized .img. No backend.

> **AP captive portal** (`ap-site/`) is not included — deferred as a future feature. It wasn't working on first hardware boot; see agent notes for details.

## First boot

One `Type=simple` background daemon (`sorteros-firstboot.service`) that loops every 60s, runs idempotent stages, never blocks boot, never errors when offline. Heavy stages (uv sync, pnpm install) wait until internet is up. See the design doc for the stage list.

## Layout

```
sorteros/
├── README.md                # this file
├── build/                   # Python image builder
│   ├── build.py
│   ├── config.toml
│   ├── chroot_apt.sh
│   ├── overlay/             # files copied into the rootfs as-is
│   └── README.md
└── sorteros-setup/          # browser-side .img customizer (SvelteKit + Vercel)
    ├── package.json
    ├── svelte.config.js
    ├── src/
    │   ├── app.css
    │   ├── lib/img-patch.ts
    │   └── routes/{+layout,+page}.svelte
    └── README.md            # deploys to setup.basically.website
```

## Versioning

Version lives in `build/config.toml` under `[output] version`. It flows into
the output filename (`sorteros-v{version}-{date}.img`). Bump it before every
build that will be flashed to hardware.

| Change type | Bump | Examples |
|---|---|---|
| New feature, new firstboot stage, new overlay file | **minor** (3.2 → 3.3) | adding `stage_clone_repo`, new AP site feature |
| Bug fix, config tweak, comment-only change | **patch** (3.2 → 3.2.1) | fixing `sh()` error swallowing, marker split fix |
| Incompatible firstboot protocol change, partition layout change | **major** (3.x → 4.0) | changing marker contract, switching base image |

Always bump before starting a build — never retroactively rename a build that was already flashed to hardware.
