# SorterOS image builder

`build.py` turns the Orange Pi vendor image into a SorterOS image. It runs as
root on Linux, natively on arm64 or on x86_64 with QEMU user emulation for
the chroot step.

## One-time setup (Ubuntu / Debian)

```bash
sudo apt-get install qemu-user-static binfmt-support cloud-guest-utils rsync e2fsprogs
```

`qemu-user-static` is only needed on x86_64; check that
`/proc/sys/fs/binfmt_misc/qemu-aarch64` exists and its flags include `F`.
The `portal` phase builds the captive portal with Node 20+ and pnpm, and
`build.py` needs Python 3.11+.

Download the base image named in `config.toml` (`[base]`) into `cache/`, or
point `SORTEROS_BASE_IMG` at it. The build checks its sha256.

## Running a build

```bash
cd software/sorteros/build
sudo python3 build.py                      # release image: first boot checks out stable
sudo python3 build.py --ref my-branch      # test image: first boot checks out my-branch
sudo python3 build.py --phase overlay      # re-run one phase
sudo python3 build.py --phase zip          # compress for a release
sudo python3 build.py --ref my-branch --from out/<previous>.img   # test image in a minute or two: skips grow + chroot
```

Output: `out/sorteros-v<version>-<date>.img`; `--phase zip` compresses it
for a GitHub release.

| phase | what it does |
| --- | --- |
| `prep` | verify the base image, copy it to `out/work.img` |
| `grow` | add 4 GiB, grow p1 and the ext4 into it, switch ext4 to `data=ordered` |
| `mount` | loop-mount the root ext4 (p1; p2 with `root_part = 2`) at `/mnt/sorteros-build`, and the vfat `/boot` (`boot_part`) under it |
| `overlay` | copy `overlay/`, bake `/etc/sorteros/{ref,version}`, hostname `sorter`, `errors=panic` in fstab, `fsck.repair=yes panic=10` on the kernel command line, optional `[display]` settings (`video=`, `fbcon=font:`, kernel log level) in `orangepiEnv.txt` |
| `portal` | build the captive portal (`../portal/`) into the rootfs |
| `chroot` | run `chroot_apt.sh` inside the rootfs (apt delta, Node, uv, avahi) |
| `finalize` | unmount, detach, rename to the versioned name |
| `zip` | compress the newest image for distribution |

## Other boards

`--config` picks the board. `config.toml` is the Orange Pi 5, `config-cm5.toml`
the CM5, `config-opi5pro.toml` the Orange Pi 5 Pro. The Pro image has a vfat
`/boot` at p1 (kernel, device tree, `orangepiEnv.txt`) and the ext4 root at
p2; `[base] boot_part` and `root_part` tell `build.py` so. Without them it
assumes one ext4 at p1.

The optional `[display]` table makes the boot readable on a small HDMI panel:

| key | effect |
| --- | --- |
| `video` | kernel `video=` argument, e.g. `HDMI-A-1:640x480@60`, for panels whose EDID lists another mode |
| `fbcon_font` | console font (`VGA8x8` or `VGA8x16`; the vendor kernel has only these two) |
| `verbosity` | kernel log level in `orangepiEnv.txt` (the vendor image uses 1, which prints almost nothing) |

The optional `[npu]` table (`url`, `filename`, `sha256`) replaces the vendor's
NPU runtime. The Orange Pi 5 Pro image ships `librknnrt` 1.4.0, which cannot run
the 2.x models Hive hands out. `rknn-toolkit-lite2` and the backend's NPU check
read `/usr/lib/librknnrt.so` and no other path, so the `overlay` phase downloads
the file into `cache/` (sha256-checked) and installs it there. The vendor file
stays as `librknnrt.so.bak`. If a dpkg package owns the path, `dpkg-divert`
keeps a later upgrade from putting the old file back (the vendor file is then
`librknnrt.so.distrib`). Keep the version in line with `rknn-toolkit-lite2` in
`software/sorter/backend/pyproject.toml`.

## What is NOT in the image

The Sorter software itself. First boot clones the repo (blobless), checks out
the newest `sorter/stable/v*` tag (or the `--ref` baked into a test image),
runs `uv sync` and `pnpm install`/`build`, installs the backend's service,
starts it, and once it answers hands port 80 to the UI, which the backend's
supervisor serves from that build. That keeps the image small and means an
image never has to be rebuilt to ship a software release. Vision models are
not in the repo either: the machine downloads Hive's default model for its
hardware after first boot.

## Test before flashing

`../test/` boots a built image in QEMU and checks it end to end. See its
README.
