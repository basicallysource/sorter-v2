# SorterOS Armbian Phase 0 Image

This directory is the Phase 0 path for a real Armbian-based RK3588 image for
the Orange Pi CM5 / Orange Pi 5 sorter machine.

The older `software/sorteros/build/` flow remasters a prebuilt vendor image.
This flow uses the official Armbian build framework plus `userpatches/` so the
kernel, bootloader, rootfs, and SorterOS payload are produced from one
repeatable build entrypoint.

## Current Facts

- Armbian supports Orange Pi 5 with vendor kernel `6.1.115`.
- Armbian `rockchip-rk3588` vendor branch uses `rk-6.1-rkr5.1`.
- The current upstream Armbian checkout does not contain an Orange Pi CM5 board
  config.
- The live CM5 tablet system reports:
  - model: `Xunlong Orange Pi Module 5(CM5) tablet Board`
  - compatible: `xunlong,orangepi-cm5-tablet rockchip,rk3588s`
  - DTB: `/boot/dtb/rockchip/rk3588s-orangepi-cm5-tablet.dtb`

## Files

- `userpatches/config/boards/orangepi-cm5-sorter.csc`
  Experimental CM5 board file for Armbian. It deliberately lives in
  `userpatches` until the board support is proven and can be upstreamed.
- `userpatches/config-sorter-cm5-vendor61.conf`
  Non-interactive Armbian build config: `BOARD=orangepi-cm5-sorter`,
  `BRANCH=vendor`, `RELEASE=noble`, minimal CLI.
- `userpatches/customize-image.sh`
  Chroot hook that copies the SorterOS overlay, runs the existing SorterOS apt
  installer, and leaves the firstboot/acceptance probes in place.
- `build-sorteros-armbian-cm5.sh`
  Prepares `armbian/build/userpatches` from this repo and invokes
  `compile.sh`.
- `dt-src/rk35xx-vendor-6.1/` and `compile-cm5-tablet-dtb.sh`
  Source and regeneration command for the CM5 tablet DTB. The current DTB is
  generated from a 6.1-compatible CM5 tablet DTS, not copied from the previous
  live 6.13 system.

## Build

Prepare an Armbian build checkout:

```bash
git clone https://github.com/armbian/build ~/Workspace/armbian-build-sorteros
```

Regenerate the CM5 tablet DTB if the source changes:

```bash
software/sorteros/armbian/compile-cm5-tablet-dtb.sh \
  --kernel-tree /path/to/linux-rockchip-rk-6.1-rkr5.1
```

Build the image:

```bash
software/sorteros/armbian/build-sorteros-armbian-cm5.sh --force-userpatches
```

Flash the image after putting the CM5 into MaskROM mode:

```bash
software/sorteros/armbian/flash-cm5-maskrom.sh --wait 60
```

The flash helper loads the RK3588 SPL, writes the image, reads the first 16 MiB
back, compares it against the image, and only then reboots the board.

The wrapper calls Armbian roughly as:

```bash
./compile.sh BOARD=orangepi-cm5-sorter BRANCH=vendor RELEASE=noble \
  BUILD_MINIMAL=yes BUILD_DESKTOP=no KERNEL_CONFIGURE=no KERNEL_BTF=no EXPERT=yes
```

## Phase 0 Acceptance

After flashing and booting the image, the target is green only when these pass
on the CM5:

```bash
cd /home/orangepi/sorter-v2/software/sorter/backend
.venv/bin/python scripts/probe_camera_transport_stack.py
.venv/bin/python scripts/probe_gstreamer_target_capture_pipeline.py --all-assigned
.venv/bin/python scripts/probe_rk3588_npu_stack.py --require-inference
ffmpeg -f lavfi -i testsrc2=size=1280x720:rate=30 -t 3 \
  -vf format=nv12 -c:v h264_rkmpp -y /tmp/rkmpp-smoke.mp4
```

Expected kernel/device evidence:

```bash
uname -r
ls -l /dev/mpp_service /dev/rga /dev/dma_heap /dev/dri/renderD128 /dev/dri/by-path/platform-fdab0000.npu-render
```

The current live 6.13 system fails this gate; this directory exists to make the
next boot candidate actually Armbian/vendor-6.1 based.
