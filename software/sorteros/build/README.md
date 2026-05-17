# SorterOS image builder

Builds a flashable SorterOS image from the Orange Pi 5 Ubuntu Jammy
**server** base image plus a provisioner that installs the sorter stack.

Reproducible. No dev-Pi snapshot. Runs in a chroot on any Linux host
(we test on Hive). Cross-arch: server base is aarch64, build host is
x86_64 → uses `qemu-aarch64-static` for binfmt emulation.

## Layout

```
build.sh           - orchestrator; copy base → grow → mount → chroot → provision → unmount → name
provision.sh       - runs INSIDE the chroot (aarch64); apt installs + sorter setup
chroot-helpers.sh  - sourced by build.sh; mount/umount/cleanup primitives
```

## Inputs

- **Base image**: `Orangepi5_1.2.2_ubuntu_jammy_server_linux6.1.99.img`
  - On the local Mac: in `~/Downloads/` (untracked)
  - On Hive (build host): `/basically/sorteros/base/...` (kept here so
    successive builds don't re-upload)

## Outputs

- `/basically/sorteros/out/sorteros-<short-sha>-<YYYY-MM-DD>.img`
- `/basically/sorteros/out/sorteros-<short-sha>-<YYYY-MM-DD>.img.zst`
  (compressed for distribution)

## What the build does NOT do (yet)

- Cloud-init + FAT boot partition for RPi Imager customization
  (deferred — see `sorter-v2-agent-notes/orange_pi/sorteros_image.md`)
- Bake in a sorter-v2 release tarball (provisioner currently clones
  the repo at HEAD; pin a tag once the repo is released)
- Sign / checksum / attach to a GitHub Release

## Building on Hive (manual run for now)

1. Upload (or have) the base image at `/basically/sorteros/base/`.
2. SSH in: `ssh root@$SORTEROS_BUILD_HOST` (Hive — set
   `SORTEROS_BUILD_HOST` from your private notes / `~/.ssh/config`).
3. `bash /basically/sorteros/build/build.sh`
4. Output lands in `/basically/sorteros/out/`.
5. `scp` the `.img.zst` back to your laptop and flash with RPi Imager
   ("Use custom").

## Do not touch the running Hive containers

The build runs entirely under `/basically/sorteros/` and never enters
`/basically/sorter/sorter-v2/software/hive/` or `/basically/traefik/`.
No Docker calls. No reboots. apt installs on the host are limited to
the build-time tools (`qemu-user-static`, `binfmt-support`,
`zstd`); these have no impact on the Docker stack.
