#!/usr/bin/env bash
# Offline-extend an already-built SorterOS .img (or .img.zst) with new
# features. Faster than a full rebuild: skips the ~25 min of apt/node/
# tailscale install we paid for the first time, and only does the delta.
#
# Current deltas applied (idempotent):
#   1. Append a FAT32 partition (label `system-boot`) at the end of the
#      image so RPi Imager can write `user-data` / `network-config` for
#      Wi-Fi / hostname / SSH customization. ext4 rootfs is NOT shrunk
#      or moved — we only grow the image and put the new partition in
#      the freed tail space.
#   2. apt install cloud-init in the rootfs (under qemu chroot) and drop
#      a NoCloud datasource config pointing at /boot/firmware/.
#   3. Add `/boot/firmware` to /etc/fstab and create the mountpoint.
#
# Stays out of: ext4 shrink, U-Boot, bootloader raw-offset region. The
# rockchip idbloader (sector 64) and u-boot.itb (sector 16384) are not
# touched; we only add space *after* the existing partition.
#
# Usage:
#   sudo ./extend.sh [--in PATH] [--out PATH] [--add-mb N] [--no-compress]
#
# Defaults assume Hive layout. --no-compress is the default for quick
# iteration; pass --compress when you want a shippable .zst.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIR/chroot-helpers.sh"

IN_DEFAULT="/basically/sorteros/out/sorteros-nogit-2026-05-17.img.zst"
OUT_DIR_DEFAULT="/basically/sorteros/out"
ADD_MB=384
COMPRESS=0

IN="$IN_DEFAULT"
OUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --in)         IN=$2; shift 2 ;;
        --out)        OUT=$2; shift 2 ;;
        --add-mb)     ADD_MB=$2; shift 2 ;;
        --compress)   COMPRESS=1; shift ;;
        --no-compress) COMPRESS=0; shift ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [[ ! -f $IN ]]; then
    echo "input image not found: $IN" >&2
    exit 1
fi

for tool in qemu-aarch64-static parted losetup e2fsck resize2fs zstd mkfs.vfat sfdisk; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "missing tool: $tool" >&2
        exit 1
    }
done

TS=$(date +%Y-%m-%d)
BASE_NAME=$(basename "$IN")
# strip .zst / .img.zst / .img → bare stem
STEM="${BASE_NAME%.zst}"; STEM="${STEM%.img}"
if [[ -z $OUT ]]; then
    OUT="$OUT_DIR_DEFAULT/sorteros-v2.2-${TS}.img"
fi
mkdir -p "$(dirname "$OUT")"

log() { echo "[extend $(date +%H:%M:%S)] $*"; }

trap cleanup_chroot EXIT

# ─── 1. Materialize raw .img ───
if [[ $IN == *.zst ]]; then
    log "decompressing $IN → $OUT"
    zstd -d -f -T0 -o "$OUT" "$IN"
else
    log "copying $IN → $OUT"
    cp --reflink=auto "$IN" "$OUT"
fi

ORIG_BYTES=$(stat -c %s "$OUT")
log "original size: $(numfmt --to=iec --suffix=B "$ORIG_BYTES")"

# ─── 2. Grow image by ADD_MB to make room for FAT at the end ───
log "growing image by ${ADD_MB} MiB"
truncate -s +"${ADD_MB}M" "$OUT"

# ─── 3. Loop-mount + inspect current partition table ───
LOOP=$(losetup --show -fP "$OUT")
log "loop: $LOOP"
parted -s "$LOOP" unit s print || true

# Identify the existing rootfs partition (assume p1, ext4).
ROOT_PART="${LOOP}p1"
[[ -b $ROOT_PART ]] || { echo "expected $ROOT_PART"; lsblk "$LOOP"; exit 1; }

# ─── 4. Add a FAT32 partition in the freed tail space ───
# Find the end sector of partition 1, start FAT one sector after that.
P1_END=$(parted -ms "$LOOP" unit s print | awk -F: '/^1:/ {gsub("s","",$3); print $3}')
TOTAL_END=$(parted -ms "$LOOP" unit s print | awk -F: '/^Disk/ && NR>1 {gsub("s","",$2); print $2}' | head -1)
# fallback for older parted format:
if [[ -z $TOTAL_END ]]; then
    TOTAL_END=$(blockdev --getsz "$LOOP")
    TOTAL_END=$((TOTAL_END - 1))
fi

# Leave 1 MiB alignment gap (2048 sectors)
P2_START=$(( ((P1_END / 2048) + 1) * 2048 ))
P2_END=$(( TOTAL_END - 1 ))

log "adding partition 2: ${P2_START}s..${P2_END}s"
parted -s "$LOOP" mkpart primary fat32 "${P2_START}s" "${P2_END}s"
parted -s "$LOOP" set 2 lba on || true

# Force kernel to re-read partition table
partprobe "$LOOP" || true
sleep 1
losetup -d "$LOOP"
LOOP=$(losetup --show -fP "$OUT")
log "re-attached loop: $LOOP"

FAT_PART="${LOOP}p2"
[[ -b $FAT_PART ]] || { echo "FAT partition $FAT_PART missing"; lsblk "$LOOP"; exit 1; }

log "formatting $FAT_PART as FAT32 (label: system-boot)"
mkfs.vfat -F 32 -n system-boot "$FAT_PART"

# ─── 5. Chroot into the rootfs to install cloud-init + configure ───
log "mounting rootfs + bind mounts for chroot"
mount_chroot "${LOOP}p1"

# Drop in a small provisioner that runs inside the chroot
cat >"$MNT/tmp/extend-provision.sh" <<'CHROOT_EOF'
#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8
APT_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold -y)

log() { echo "[extend-provision $(date -u +%H:%M:%S)] $*"; }

# Some Orange Pi base images don't have /etc/resolv.conf inside the
# rootfs (it's a runtime symlink to systemd-resolved). The chroot bind
# mount may have provided one already; if not, drop a minimal one for
# apt.
if [[ ! -s /etc/resolv.conf ]]; then
    echo "nameserver 1.1.1.1" > /etc/resolv.conf
    echo "nameserver 8.8.8.8" >> /etc/resolv.conf
fi

log "apt update"
apt-get update -y

log "installing cloud-init"
apt-get install "${APT_OPTS[@]}" --no-install-recommends cloud-init

log "writing /etc/cloud/cloud.cfg.d/99-sorteros.cfg"
mkdir -p /etc/cloud/cloud.cfg.d
cat >/etc/cloud/cloud.cfg.d/99-sorteros.cfg <<'EOF'
# SorterOS — restrict cloud-init to the NoCloud datasource and read
# the seed files from the FAT partition mounted at /boot/firmware.
# Anything else (EC2, Azure, GCE probes) wastes 30+s on first boot.
datasource_list: [ NoCloud, None ]
datasource:
  NoCloud:
    seedfrom: /boot/firmware/
# Don't let cloud-init's network module overwrite NetworkManager
# config. We consume `network-config` ourselves via a hook below if
# it's present; if it isn't, NetworkManager wins.
network:
  config: disabled
EOF

log "creating /boot/firmware mountpoint"
mkdir -p /boot/firmware

log "adding /boot/firmware to /etc/fstab"
if ! grep -q "^LABEL=system-boot" /etc/fstab; then
    cat >>/etc/fstab <<'EOF'
LABEL=system-boot  /boot/firmware  vfat  defaults,noatime  0  2
EOF
fi

# ─── network-config consumer hook ───
# cloud-init's network module is disabled above (so it doesn't fight
# NetworkManager). But we still want to honor what RPi Imager dropped
# in /boot/firmware/network-config. Lightweight oneshot: on first
# boot, if the FAT partition has Wi-Fi credentials, hand them to
# nmcli.
install -m 0755 /dev/stdin /usr/local/sbin/sorteros-apply-network-config.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
SEED=/boot/firmware/network-config
STAMP=/var/lib/sorteros/network-config-applied
mkdir -p "$(dirname "$STAMP")"
[[ -f $STAMP ]] && exit 0
[[ -f $SEED ]] || exit 0
# Parse a minimal subset of RPi Imager's network-config: it produces a
# netplan-style YAML with one Wi-Fi network and a password (or PSK).
SSID=$(awk '/^[[:space:]]+[A-Za-z0-9_-]+:[[:space:]]*$/{gsub(":",""); name=$1} /password:/{print name; exit}' "$SEED" || true)
PSK=$(awk -F'"' '/password:/{print $2; exit}' "$SEED" || true)
if [[ -z $SSID || -z $PSK ]]; then
    # Try `psk:` form
    SSID=$(awk '/^[[:space:]]+[A-Za-z0-9_-]+:[[:space:]]*$/{gsub(":",""); name=$1} /psk:/{print name; exit}' "$SEED" || true)
    PSK=$(awk -F'"' '/psk:/{print $2; exit}' "$SEED" || true)
fi
if [[ -n $SSID && -n $PSK ]]; then
    if command -v nmcli >/dev/null 2>&1; then
        nmcli device wifi connect "$SSID" password "$PSK" || true
    else
        # Fallback: wpa_supplicant + dhclient via netplan if NM absent
        mkdir -p /etc/netplan
        cat >/etc/netplan/60-sorteros-wifi.yaml <<NETPLAN
network:
  version: 2
  wifis:
    wlan0:
      dhcp4: true
      access-points:
        "$SSID":
          password: "$PSK"
NETPLAN
        chmod 600 /etc/netplan/60-sorteros-wifi.yaml
        netplan apply || true
    fi
fi
touch "$STAMP"
EOF

install -m 0644 /dev/stdin /etc/systemd/system/sorteros-apply-network-config.service <<'EOF'
[Unit]
Description=SorterOS — apply RPi Imager Wi-Fi customization on first boot
After=local-fs.target network-pre.target
Before=network-online.target
ConditionPathExists=/boot/firmware/network-config
ConditionPathExists=!/var/lib/sorteros/network-config-applied

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sorteros-apply-network-config.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl enable sorteros-apply-network-config.service

# cloud-init itself handles hostname, user, ssh enable, etc. from
# user-data. Enable its services explicitly (apt should do this but
# making sure under qemu chroot).
systemctl enable cloud-init-local.service cloud-init.service cloud-config.service cloud-final.service 2>/dev/null || true

# ─── split firstboot: fast (blocks SSH) + deps (background, slow) ───
# Original sorteros-firstboot.service blocked SSH for 10–15 min while
# `uv sync` and `pnpm install` ran. Replace with a fast unit that only
# does the things SSH needs (host keys, growpart) and a separate
# background unit for the heavy deps.
log "installing split firstboot units"

install -m 0755 /dev/stdin /usr/local/sbin/sorteros-firstboot-fast.sh <<'EOF'
#!/usr/bin/env bash
# Fast first-boot. Blocks SSH while it runs. Target: < 10 s.
# Only things that must happen before SSH/network can be useful.
set -euo pipefail
STAMP=/var/lib/sorteros/firstboot-fast-done
mkdir -p "$(dirname "$STAMP")"
[[ -f $STAMP ]] && exit 0
log() { echo "[sorteros-firstboot-fast] $*"; }

# SSH host keys
if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
    log "regenerating SSH host keys"
    ssh-keygen -A
fi

# Grow rootfs to fill the card (safety net; cloud-init's growpart
# module also does this, but it runs later).
ROOT_DEV=$(findmnt -no SOURCE /)
ROOT_DISK=$(lsblk -no PKNAME "$ROOT_DEV" | head -1)
PART_NUM=$(echo "$ROOT_DEV" | grep -oE '[0-9]+$')
if command -v growpart >/dev/null 2>&1 && [[ -n $ROOT_DISK && -n $PART_NUM ]]; then
    log "growing /dev/$ROOT_DISK partition $PART_NUM"
    growpart "/dev/$ROOT_DISK" "$PART_NUM" || true
    resize2fs "$ROOT_DEV" || true
fi

touch "$STAMP"
log "done"
EOF

install -m 0755 /dev/stdin /usr/local/sbin/sorteros-firstboot-deps.sh <<'EOF'
#!/usr/bin/env bash
# Slow first-boot. Runs in background AFTER multi-user.target is up,
# so SSH is reachable while this churns. Backend / UI services will
# fail-restart loop until this finishes — that's expected.
set -euo pipefail
STAMP=/var/lib/sorteros/firstboot-deps-done
mkdir -p "$(dirname "$STAMP")"
[[ -f $STAMP ]] && exit 0
log() { echo "[sorteros-firstboot-deps] $*"; }

# swapfile (8 GB; recreate if missing — scrub deletes it)
if [[ ! -f /swapfile ]] && grep -q "^/swapfile" /etc/fstab; then
    log "recreating /swapfile (8 GB)"
    fallocate -l 8G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=8192 status=progress
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
fi

# uv sync (slow — downloads PyTorch CPU wheels, ~10 min on real Pi)
SOFTWARE_DIR=/home/orangepi/sorter-v2/software
if [[ -d "$SOFTWARE_DIR/sorter/backend" && ! -d "$SOFTWARE_DIR/sorter/backend/.venv" ]]; then
    log "running uv sync"
    su - orangepi -c "cd $SOFTWARE_DIR/sorter/backend && uv sync" || \
        log "WARN: uv sync failed"
fi

# pnpm install (3–5 min)
if [[ -d "$SOFTWARE_DIR/sorter/frontend" && ! -d "$SOFTWARE_DIR/sorter/frontend/node_modules" ]]; then
    log "running pnpm install"
    su - orangepi -c "cd $SOFTWARE_DIR/sorter/frontend && pnpm install --frozen-lockfile" || \
        log "WARN: pnpm install failed"
fi

touch "$STAMP"
log "done"
EOF

install -m 0644 /dev/stdin /etc/systemd/system/sorteros-firstboot-fast.service <<'EOF'
[Unit]
Description=SorterOS first-boot (fast — host keys, growpart). Blocks SSH.
After=local-fs.target
Before=ssh.service sshd.service network-pre.target
ConditionPathExists=!/var/lib/sorteros/firstboot-fast-done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sorteros-firstboot-fast.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

install -m 0644 /dev/stdin /etc/systemd/system/sorteros-firstboot-deps.service <<'EOF'
[Unit]
Description=SorterOS first-boot (deps — swap, uv sync, pnpm install). Background.
After=multi-user.target network-online.target
Wants=network-online.target
ConditionPathExists=!/var/lib/sorteros/firstboot-deps-done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sorteros-firstboot-deps.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal
# Don't hold up boot; this unit can take 15+ min on a real Pi.
TimeoutStartSec=infinity

[Install]
WantedBy=multi-user.target
EOF

# Disable the old monolithic firstboot service (if v2.1's provisioner
# installed it) and enable the two new ones.
systemctl disable sorteros-firstboot.service 2>/dev/null || true
rm -f /etc/systemd/system/multi-user.target.wants/sorteros-firstboot.service
systemctl enable sorteros-firstboot-fast.service
systemctl enable sorteros-firstboot-deps.service

log "cleaning apt caches"
apt-get clean
rm -rf /var/lib/apt/lists/*

log "extend-provision done"
CHROOT_EOF
chmod +x "$MNT/tmp/extend-provision.sh"

log "running extend-provision inside chroot"
chroot "$MNT" /tmp/extend-provision.sh
rm -f "$MNT/tmp/extend-provision.sh"

# ─── 6. Drop a README + a *commented* example user-data into FAT ───
log "populating FAT partition"
FAT_MNT=$(mktemp -d)
mount "$FAT_PART" "$FAT_MNT"
cat >"$FAT_MNT/README.txt" <<'EOF'
SorterOS boot partition.

Files on this partition are read by cloud-init on first boot:

  user-data       Cloud-init NoCloud config (hostname, user, ssh, etc.)
  meta-data       NoCloud datasource metadata (can be empty)
  network-config  Wi-Fi credentials (netplan format). Optional.

Raspberry Pi Imager writes these for you when you use "Customise" in
the flash dialog. If you flash by hand, drop your own files here.

After first boot completes you can ignore this partition; cloud-init
leaves a marker in /var/lib/cloud/ and won't re-apply.
EOF

# Empty meta-data — required by NoCloud spec even if blank
: > "$FAT_MNT/meta-data"

# Commented example so a hand-flashed image still boots without Imager.
cat >"$FAT_MNT/user-data.example" <<'EOF'
#cloud-config
# Rename this file to `user-data` to apply on next boot.
hostname: sorter
manage_etc_hosts: true
users:
  - name: orangepi
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: [adm, dialout, plugdev, video, audio, sudo, netdev]
    shell: /bin/bash
    lock_passwd: false
    # Replace with your own hashed password (mkpasswd --method=SHA-512).
    # passwd: $6$...
ssh_pwauth: true
EOF

cat >"$FAT_MNT/network-config.example" <<'EOF'
# Rename to `network-config` to apply on next boot.
version: 2
wifis:
  wlan0:
    dhcp4: true
    access-points:
      "your-wifi-ssid":
        password: "your-wifi-password"
EOF

sync
umount "$FAT_MNT"
rmdir "$FAT_MNT"

# ─── 7. Tear down chroot ───
log "syncing + unmounting"
sync
cleanup_chroot
trap - EXIT

log "image ready: $OUT ($(du -h "$OUT" | awk '{print $1}'))"

if [[ $COMPRESS == 1 ]]; then
    log "compressing → $OUT.zst (this is the slow part, ~30+ min)"
    zstd --rm -15 -T0 "$OUT"
    log "done: $OUT.zst ($(du -h "$OUT.zst" | awk '{print $1}'))"
else
    log "skipping compression (use --compress for shippable .zst)"
fi
