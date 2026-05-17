# Sourced by build.sh. Mount/umount/cleanup primitives for chroot work
# on a partition inside a raw .img. Not standalone-runnable.

set -euo pipefail

LOOP=""
MNT=""

cleanup_chroot() {
    local rc=$?
    if [[ -n $MNT && -d $MNT ]]; then
        for sub in dev/pts dev proc sys run tmp; do
            mountpoint -q "$MNT/$sub" 2>/dev/null && umount -lf "$MNT/$sub" || true
        done
        mountpoint -q "$MNT" 2>/dev/null && umount -lf "$MNT" || true
        rmdir "$MNT" 2>/dev/null || true
    fi
    if [[ -n $LOOP ]] && losetup "$LOOP" >/dev/null 2>&1; then
        losetup -d "$LOOP" || true
    fi
    return $rc
}

setup_loop() {
    local img=$1
    LOOP=$(losetup --show -fP "$img")
    sleep 1
    if [[ ! -b "${LOOP}p1" ]]; then
        echo "no p1 partition on $LOOP — image layout differs from expected" >&2
        lsblk "$LOOP" >&2
        return 1
    fi
}

mount_chroot() {
    local part=$1
    MNT=$(mktemp -d /tmp/sorteros-chroot.XXXXXX)
    mount "$part" "$MNT"
    mount --bind /dev "$MNT/dev"
    mount --bind /dev/pts "$MNT/dev/pts"
    mount -t proc proc "$MNT/proc"
    mount -t sysfs sys "$MNT/sys"
    mount -t tmpfs tmp "$MNT/run"
    mount -t tmpfs tmp "$MNT/tmp"

    if [[ ! -e "$MNT/usr/bin/qemu-aarch64-static" ]]; then
        cp /usr/bin/qemu-aarch64-static "$MNT/usr/bin/qemu-aarch64-static"
    fi
    cp /etc/resolv.conf "$MNT/etc/resolv.conf"
}

grow_image() {
    local img=$1
    local target_gb=$2
    local current
    current=$(stat -c %s "$img")
    local target=$((target_gb * 1024 * 1024 * 1024))
    if [[ $current -ge $target ]]; then
        echo "image already >= ${target_gb}G ($current bytes)"
        return 0
    fi
    echo "growing image to ${target_gb}G"
    truncate -s "${target_gb}G" "$img"

    local loop
    loop=$(losetup --show -fP "$img")
    sleep 1
    parted -s "$loop" resizepart 1 100%
    e2fsck -fy "${loop}p1" || true
    resize2fs "${loop}p1"
    losetup -d "$loop"
}
