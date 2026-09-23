#!/usr/bin/env bash
# Boot a SorterOS image in QEMU so first boot can be watched end to end
# without flashing a card.
#
# The Orange Pi's own kernel only runs on its hardware, so this boots the
# image's root filesystem with a stock Ubuntu arm64 kernel on QEMU's "virt"
# machine. Everything above the kernel is the image: systemd, onboarding,
# firstboot, the Sorter services. There is no NPU, camera, Wi-Fi or control
# board, so the machine comes up the way a board with an Ethernet cable and
# nothing plugged in would.
#
# The image file is never modified: the VM writes to a copy-on-write disk in
# the work directory. Guest ports 80 (status page, then UI), 8000 (backend)
# and 22 are forwarded to HTTP_PORT, API_PORT and SSH_PORT on this host.
#
#   ./boot.sh out/sorteros-v4.1.0-2026-09-23.img          # starts in the background
#   ./check.py boot                                        # watch it and check it
#   kill "$(cat work/qemu.pid)"                            # stop it
#
# On an x86_64 host the whole guest is emulated (slow: first boot takes an
# hour or more); on an arm64 Linux host with /dev/kvm it runs at native speed.
set -euo pipefail

IMG=${1:?usage: boot.sh <sorteros.img> [workdir]}
WORK=${2:-$(cd "$(dirname "$0")" && pwd)/work}
HTTP_PORT=${HTTP_PORT:-8080}
API_PORT=${API_PORT:-8000}
SSH_PORT=${SSH_PORT:-2222}
SMP=${SMP:-4}
MEM=${MEM:-4096}
DISK=${DISK:-16G}
UBUNTU=https://cloud-images.ubuntu.com/jammy/current/unpacked

mkdir -p "$WORK"
if [ -f "$WORK/qemu.pid" ] && kill -0 "$(cat "$WORK/qemu.pid")" 2>/dev/null; then
    echo "a VM from $WORK is already running (pid $(cat "$WORK/qemu.pid"))" >&2
    exit 1
fi
[ -f "$WORK/vmlinuz" ] || curl -fsSL -o "$WORK/vmlinuz" "$UBUNTU/jammy-server-cloudimg-arm64-vmlinuz-generic"
[ -f "$WORK/initrd" ] || curl -fsSL -o "$WORK/initrd" "$UBUNTU/jammy-server-cloudimg-arm64-initrd-generic"

# A fresh copy-on-write disk each run, sized like an SD card so grow-rootfs
# and the swap stage have room.
rm -f "$WORK/disk.qcow2" "$WORK/console.log"
qemu-img create -q -f qcow2 -F raw -b "$(realpath "$IMG")" "$WORK/disk.qcow2" "$DISK"

if [ "$(uname -m)" = aarch64 ] && [ -w /dev/kvm ]; then
    ACCEL=(-accel kvm -cpu host)
else
    ACCEL=(-accel tcg,thread=multi -cpu max)
fi

qemu-system-aarch64 -M virt "${ACCEL[@]}" -smp "$SMP" -m "$MEM" \
    -kernel "$WORK/vmlinuz" -initrd "$WORK/initrd" \
    -append "root=LABEL=opi_root rw console=ttyAMA0 fsck.repair=yes panic=10" \
    -drive "file=$WORK/disk.qcow2,if=virtio,format=qcow2" \
    -netdev "user,id=n0,hostfwd=tcp::$HTTP_PORT-:80,hostfwd=tcp::$API_PORT-:8000,hostfwd=tcp::$SSH_PORT-:22" \
    -device virtio-net-pci,netdev=n0 \
    -display none -monitor none -serial "file:$WORK/console.log" \
    -pidfile "$WORK/qemu.pid" -daemonize

echo "booting (pid $(cat "$WORK/qemu.pid")); console: $WORK/console.log"
echo "status page / UI: http://localhost:$HTTP_PORT   backend: http://localhost:$API_PORT   ssh: -p $SSH_PORT root@localhost"
