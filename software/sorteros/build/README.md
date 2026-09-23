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
```

Output: `out/sorteros-v<version>-<date>.img`, and `--phase zip` compresses it
for a GitHub release.

| phase | what it does |
| --- | --- |
| `prep` | verify the base image, copy it to `out/work.img` |
| `grow` | add 4 GiB, grow p1 and the ext4 into it, switch ext4 to `data=ordered` |
| `mount` | loop-mount p1 at `/mnt/sorteros-build` |
| `overlay` | copy `overlay/`, bake `/etc/sorteros/{ref,version}`, hostname `sorter`, `errors=panic` in fstab, `fsck.repair=yes panic=10` on the kernel command line |
| `portal` | build the captive portal (`../portal/`) into the rootfs |
| `chroot` | run `chroot_apt.sh` inside the rootfs (apt delta, Node, uv, avahi) |
| `finalize` | unmount, detach, rename to the versioned name |
| `zip` | compress the newest image for distribution |

## What is NOT in the image

The Sorter software itself. First boot clones the repo (blobless), checks out
the newest `sorter/stable/v*` tag (or the `--ref` baked into a test image),
runs `uv sync` and `pnpm install`/`build`, installs the services, and hands
port 80 to the UI. That keeps the image small and means an image never has to
be rebuilt to ship a software release. Vision models are not in the repo
either: the machine downloads Hive's default model for its hardware after
first boot.

## Test before flashing

`../test/` boots a built image in QEMU and checks it end to end. See its
README.
