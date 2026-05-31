# v3 builder

Python image builder. Runs locally on the M2 Mac inside a colima Linux VM
(arm64 native — no qemu emulation, no Hive).

## One-time setup on the Mac

```bash
brew install colima docker
colima start --arch aarch64 --cpu 4 --memory 8 --mount-type virtiofs \
    --mount $HOME/Documents/GitHub/sorter-v2-03:w
```

`colima` gives you a real Linux VM with `/dev/loop*`, `mount`, `chroot`,
all of it. The repo is bind-mounted so the build sees source files
directly.

## Running a build

```bash
# Inside the colima VM (colima ssh):
cd ~/sorter-v2-03/software/sorteros/v3/build
sudo /opt/homebrew/opt/python@3.11/libexec/bin/python build.py
```

Or with phases for fast iteration:

```bash
sudo python build.py --phase chroot   # re-run only the apt step
sudo python build.py --phase overlay  # re-run only the overlay copy
```

Output: `out/sorteros-v3-<date>.img` in the repo dir.

## Target wall-time

| phase | target | what it does |
| --- | --- | --- |
| `prep` | ~5 s | `cp` base image from `cache/` → `out/work.img` |
| `mount` | ~5 s | `losetup -fP`, `e2fsck -fy`, `mount` p1 at `/mnt/sorteros-build` |
| `overlay` | ~2 s | `rsync -aH` `overlay/` → rootfs; bake `/etc/sorteros/branch` |
| `portal` | ~15 s | `pnpm build` the SorterOS captive portal, copy backend + static bundle into rootfs |
| `chroot` | ~60 s | bind `/dev /proc /sys /dev/pts`, run `chroot_apt.sh`, unbind |
| `finalize` | ~5 s | `umount`, `losetup -d`, rename `work.img` → `sorteros-v4-<date>.img` |
| **total** | **< 90 s** | (assumes base img is cached and arm64-native; under qemu add ~3 min) |

The base image is downloaded once and cached under `cache/`. Subsequent
builds skip the download entirely.

## What is NOT in the image

- `uv sync` — deferred to the firstboot daemon (~5 GB PyTorch wheels).
- `pnpm install` — deferred to the firstboot daemon.
- Repo clone of `sorter-v2` — deferred to the firstboot daemon.

The point of deferral isn't speed-of-build (the chroot path is native
arm64 anyway), it's image *size*. Keeping these out of the image takes
the .img from ~8 GB → < 4 GB raw.

## See also

- `../README.md` — v3 overview
- `sorter-v2-agent-notes/orange_pi/sorteros_v3.md` — full design doc
