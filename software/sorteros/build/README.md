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
python build.py --config config-cm5-vendor61.toml --phase fetch-base
sudo python build.py --phase chroot   # re-run only the apt step
sudo python build.py --phase overlay  # re-run only the overlay copy
```

Output: `out/sorteros-v3-<date>.img` in the repo dir.

## RK3588 Acceleration Gate

The hardware WebRTC camera transport and on-device inference need a Rockchip
vendor multimedia kernel that exposes MPP/RGA/DMA and NPU runtime devices such
as `/dev/mpp_service`, `/dev/rga`, `/dev/dma_heap`, `/dev/dri/renderD128`, and
the RKNPU render node. The OrangePi CM5 Tablet 25.02 base currently boots Linux 6.13.0
and does not expose the multimedia devices, even after installing the Rockchip
multimedia PPA packages in `chroot_apt.sh`.

Use `config-cm5-vendor61.toml` as the experimental CM5 Ubuntu 24.04 / Linux 6.1
candidate. The build bakes `/etc/sorteros/camera-transport-target.json` into
that image; firstboot copies the contract's backend env into `software/.env`,
including `SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC=1`. Firstboot also writes a
non-fatal runtime summary to
`/var/lib/sorteros/camera-transport-status.json`, including missing device
nodes, packages, kernel-release requirements, machine architecture, and probe
gates. This is intentional: Rockchip userspace packages alone are not enough if
the booted kernel family does not expose MPP/RGA/DMA devices.

The vendor-6.1 contract is deliberately stricter than "ffmpeg advertises
`h264_rkmpp`": it also requires the runtime encode probe, RGA+RKMPP runtime
probe, `/dev/video*` handle audit, raw-ring calibration availability, the final
hardware scale/convert + zero-copy source pipeline gate, and an RKNNLite NPU
inference smoke test. A staging path that pipes CPU BGR frames into
`h264_rkmpp` must stay red, and an image with only Python RKNN packages but no
usable NPU runtime must also stay red.

After first boot and firstboot dependency install, validate it with:

```bash
cd /home/orangepi/sorter-v2/software/sorter/backend
.venv/bin/python scripts/probe_camera_transport_stack.py
```

The probe output also surfaces the firstboot status file when it exists, so one
command shows both the baked image contract and the latest boot-time verdict.

The capture-handle acceptance probe can run even while the encoder stack is
still red:

```bash
cd /home/orangepi/sorter-v2/software/sorter/backend
.venv/bin/python scripts/probe_camera_handle_stability.py --role c_channel_2 --clients 2
```

It keeps several feed clients alive and verifies that the `/dev/videoN` handle
count and capture instance count do not increase.

The integrated capture-pipeline probe checks the final source shape: one
GStreamer/Rockchip capture owner with a raw-ring branch and an H.264 WebRTC
branch. It also guards against a direct ffmpeg `/dev/videoN` pipeline becoming
accidentally accepted:

```bash
cd /home/orangepi/sorter-v2/software/sorter/backend
.venv/bin/python scripts/probe_gstreamer_target_capture_pipeline.py --all-assigned
```

The calibration-ring acceptance probe verifies that exposure/color/zone
calibration reads a fresh frame from the shared raw ring buffer and does not
open a second capture:

```bash
cd /home/orangepi/sorter-v2/software/sorter/backend
.venv/bin/python scripts/probe_camera_calibration_ring.py --all-assigned
```

During bring-up, use `--roles c_channel_2,c_channel_3` to check only the
currently connected C-channel cameras.

Once the transport probe is green, run the multi-view encoder acceptance probe:

```bash
cd /home/orangepi/sorter-v2/software/sorter/backend
.venv/bin/python scripts/probe_webrtc_view_scaling.py --role c_channel_2 --views 3
```

That probe opens several WebRTC peers for the same physical camera and verifies
that active peers fan out from one hardware source and one encoder. It also
reports the backend process CPU delta between the before/after runtime
snapshots, so encoder/view scaling can be compared across images.

The NPU acceptance probe is part of the same Phase-0 gate:

```bash
cd /home/orangepi/sorter-v2/software/sorter/backend
.venv/bin/python scripts/probe_rk3588_npu_stack.py --require-inference
```

`--require-inference` requires the RKNPU node (`/dev/rknpu` on older kernels or
`/dev/dri/by-path/platform-fdab0000.npu-render` on the DRM driver), importable `rknnlite.api`, the
configured RKNN smoke model, and a real `RKNNLite.load_rknn` +
`init_runtime` + `inference` round trip.

Exit code `0` means the booted system satisfies the target camera transport gate. Exit code
`2` means the probe ran but the kernel/userland stack, active UI transport, or
both are still outside the target architecture. The default exit gate is strict:
it requires the hardware WebRTC/H.264 path *and* zero active legacy per-view
MJPEG clients. Use `--readiness-only` only when you want to isolate the
kernel/encoder bringup from legacy-client migration noise.

## Target wall-time

| phase | target | what it does |
| --- | --- | --- |
| `fetch-base` | download-bound | download/decompress/checksum the configured base image; no root required |
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
