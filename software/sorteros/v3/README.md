# SorterOS v3 — fork, experiment

> **2026-05-17.** Active line of experimentation. Forked from v2.7.
> Goal: delete the FAT-partition surgery, drop RPi Imager as a
> dependency, optimize the build for fast iteration on the M2 Mac.
>
> Full design doc: `sorter-v2-agent-notes/orange_pi/sorteros_v3.md`.
> Read it before touching anything here.

## The three legs

1. **`ap-site/`** — captive portal that runs on the Pi when no Wi-Fi
   is configured. User joins the Pi's AP from their phone, picks a
   Wi-Fi from a list, types the password, done.
2. **`sorteros-setup/`** — pure-browser .img customizer. SvelteKit +
   Tailwind, deployed to Vercel at <https://setup.basically.website>.
   User uploads an image, fills out a form (Wi-Fi, hostname, SSH keys),
   downloads a customized .img. No backend. Design rules inherited from
   the sorter frontend (`software/sorter/frontend/CLAUDE.md`).
3. **`build/`** — Python builder. Runs locally on the M2 Mac (via
   colima for the Linux side). No qemu emulation. No Hive. Target
   wall-time < 3 min.

## First boot

One `Type=simple` background daemon (`sorteros-firstboot.service`)
that loops every 60s, runs idempotent stages, never blocks boot,
never errors when offline. Heavy stages (uv sync, pnpm install) just
wait until internet is up. See the design doc for the stage list.

## Status

- 2026-05-17: scaffolded, nothing built yet.
- First milestone: `build.py` produces a bootable image on the M2.

## Layout

```
v3/
├── README.md                # this file
├── build/                   # Python image builder
│   ├── build.py
│   ├── config.toml
│   ├── chroot_apt.sh
│   ├── overlay/             # files copied into the rootfs as-is
│   └── README.md
├── ap-site/                 # captive portal served on the Pi
│   ├── app.py
│   ├── templates/
│   ├── static/
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

Rules (pick the right level automatically):

| Change type | Bump | Examples |
|---|---|---|
| New feature, new firstboot stage, new overlay file | **minor** (3.2 → 3.3) | adding `stage_clone_repo`, new AP site feature |
| Bug fix, config tweak, comment-only change | **patch** (3.2 → 3.2.1) | fixing `sh()` error swallowing, marker split fix |
| Incompatible firstboot protocol change, partition layout change | **major** (3.x → 4.0) | changing marker contract, switching base image |

Always bump before starting a build — never retroactively rename a build that
was already flashed to hardware.

## When v3 graduates

If hardware testing confirms the strategy works:
- Delete `software/sorteros/build/` (v2 extend.sh / build.sh / etc.)
- Delete `software/sorteros/{prep-image,scrub,firstboot,find-pi}.sh`,
  `software/sorteros/capture.md`, `software/sorteros/scrub-paths.txt`,
  `software/sorteros/sorteros-firstboot.service`, `test-scrub.sh`.
- Move everything under `v3/` up one level.
- Update the agent notes: collapse v1.x and v2.x docs into a
  single "historical" section in `sorteros_v3.md`, delete the rest.
