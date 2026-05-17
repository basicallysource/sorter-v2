#!/usr/bin/env bash
# SorterOS image builder. Runs on a Linux host (we test on Hive,
# x86_64 + qemu-user-static for aarch64 emulation).
#
# Usage:
#   sudo ./build.sh [--base PATH] [--out-dir DIR] [--size GB]
#
# Defaults are tuned for Hive layout under /basically/sorteros/.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIR/chroot-helpers.sh"

BASE="/basically/sorteros/base/Orangepi5_1.2.2_ubuntu_jammy_server_linux6.1.99.img"
OUT_DIR="/basically/sorteros/out"
SIZE_GB=8
KEEP_WORK=0
SKIP_PROVISION=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base) BASE=$2; shift 2 ;;
        --out-dir) OUT_DIR=$2; shift 2 ;;
        --size) SIZE_GB=$2; shift 2 ;;
        --keep-work) KEEP_WORK=1; shift ;;
        --skip-provision) SKIP_PROVISION=1; shift ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [[ ! -f $BASE ]]; then
    echo "base image not found: $BASE" >&2
    exit 1
fi

for tool in qemu-aarch64-static parted kpartx losetup e2fsck resize2fs zstd; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "missing tool: $tool" >&2
        exit 1
    }
done

mkdir -p "$OUT_DIR"
TS=$(date +%Y-%m-%d)
TAG=$(cd "$SCRIPT_DIR"/../../.. && git rev-parse --short HEAD 2>/dev/null || echo "nogit")
WORK="$OUT_DIR/work-$TAG-$TS.img"
OUT="$OUT_DIR/sorteros-$TAG-$TS.img"

log() { echo "[build $(date +%H:%M:%S)] $*"; }

trap cleanup_chroot EXIT

log "copying base → $WORK"
cp --reflink=auto "$BASE" "$WORK"

log "growing to ${SIZE_GB}G"
grow_image "$WORK" "$SIZE_GB"

log "loop-mounting"
setup_loop "$WORK"

log "mounting partition + bind mounts"
mount_chroot "${LOOP}p1"

if [[ $SKIP_PROVISION == 0 ]]; then
    # Source-overlay for the sorteros/ tree. When working from the Mac
    # repo, $SCRIPT_DIR/.. is software/sorteros/ and directly contains
    # firstboot.sh. When running on Hive (sources scp'd separately), the
    # overlay lives at $SCRIPT_DIR/../sorteros-src/. Detect both.
    SRC_OVERLAY=""
    if [[ -f "$SCRIPT_DIR/../sorteros-src/firstboot.sh" ]]; then
        SRC_OVERLAY="$(cd "$SCRIPT_DIR/../sorteros-src" && pwd)"
    elif [[ -f "$SCRIPT_DIR/../firstboot.sh" ]]; then
        SRC_OVERLAY="$(cd "$SCRIPT_DIR/.." && pwd)"
    fi
    if [[ -n $SRC_OVERLAY ]]; then
        log "copying sorteros source overlay into chroot from $SRC_OVERLAY"
        mkdir -p "$MNT/tmp/sorteros-src"
        # Skip the build/ dir if it happens to live next door
        find "$SRC_OVERLAY" -maxdepth 1 -mindepth 1 -not -name build \
            -exec cp -a {} "$MNT/tmp/sorteros-src/" \;
    else
        echo "WARN: no sorteros overlay located; provisioner will rely on the cloned repo only" >&2
    fi

    log "copying provisioner into chroot"
    install -m 0755 "$SCRIPT_DIR/provision.sh" "$MNT/tmp/provision.sh"

    log "running provisioner inside chroot"
    chroot "$MNT" /tmp/provision.sh

    rm -f "$MNT/tmp/provision.sh"
    rm -rf "$MNT/tmp/sorteros-src"
fi

log "syncing + unmounting"
sync
cleanup_chroot
trap - EXIT

log "renaming to $OUT"
mv "$WORK" "$OUT"

log "compressing → $OUT.zst"
zstd --rm -19 -T0 "$OUT"

log "done: $OUT.zst ($(du -h "$OUT.zst" | awk '{print $1}'))"
