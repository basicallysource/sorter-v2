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

# Auto-source a co-located .env (gitignored). Lets you keep build-time
# config (auth keys, default branch, etc.) on the Hive build host
# without putting them on the command line.
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
fi

IN_DEFAULT="/basically/sorteros/out/sorteros-nogit-2026-05-17.img.zst"
OUT_DIR_DEFAULT="/basically/sorteros/out"
ADD_MB=384
COMPRESS=0
# Preserve any value sourced from .env above. --branch overrides if passed.
SORTER_BRANCH="${SORTER_BRANCH:-}"

IN="$IN_DEFAULT"
OUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --in)         IN=$2; shift 2 ;;
        --out)        OUT=$2; shift 2 ;;
        --add-mb)     ADD_MB=$2; shift 2 ;;
        --compress)   COMPRESS=1; shift ;;
        --no-compress) COMPRESS=0; shift ;;
        --branch)     SORTER_BRANCH=$2; shift 2 ;;
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
    OUT="$OUT_DIR_DEFAULT/sorteros-v2.5-${TS}.img"
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

# v2.5: NO FAT partition. v2.4 put FAT immediately after ext4, which
# blocked growpart from extending the rootfs on first boot — cloud-init
# then died with disk-full on a >8GB SD card. Single-partition layout
# means growpart works without games and ext4 fills the actual card.
# Wi-Fi customization no longer goes through cloud-init/Imager; a baked
# fallback NM connection covers the dev/bring-up case (see below).

# ─── 2. Loop-mount the existing image ───
LOOP=$(losetup --show -fP "$OUT")
log "loop: $LOOP"
parted -s "$LOOP" unit s print || true

# Identify the existing rootfs partition (assume p1, ext4).
ROOT_PART="${LOOP}p1"
[[ -b $ROOT_PART ]] || { echo "expected $ROOT_PART"; lsblk "$LOOP"; exit 1; }

# ─── 3. Chroot into the rootfs ───
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

# v2.5: cloud-init / FAT seed flow removed. Imager's customization
# doesn't reliably find a non-partition-1 FAT, and the FAT-after-ext4
# layout blocked rootfs growth (cloud-init then OOMed on disk on the
# first boot of a >8 GB card). Wi-Fi for dev/bring-up comes from the
# baked-in NM connection (sorteros-fallback-wifi) below.

# Purge cloud-init (left over from v2.4 inheritance) so it doesn't
# spend time probing data sources we no longer plumb anything to.
if dpkg -l cloud-init 2>/dev/null | grep -q '^ii'; then
    log "removing cloud-init (no longer used)"
    apt-get purge -y cloud-init || true
    rm -rf /etc/cloud /var/lib/cloud
    # Strip the /boot/firmware fstab entry the v2.4 build wrote
    sed -i '/^LABEL=system-boot/d' /etc/fstab
    # Disable any lingering symlinks
    rm -f /etc/systemd/system/multi-user.target.wants/sorteros-apply-network-config.service
fi

# ─── AP6275P Wi-Fi overlay (Orange Pi 5 official M.2 Wi-Fi module) ───
# Without this line in /boot/orangepiEnv.txt, U-Boot never loads the
# DTB overlay for the AP6275P chip and the kernel doesn't see wlan0.
# Confirmed missing on the Jammy server base.
ENV_FILE=/boot/orangepiEnv.txt
if [[ -f "$ENV_FILE" ]]; then
    log "ensuring AP6275P Wi-Fi overlay is enabled in $ENV_FILE"
    if ! grep -q '^overlays=' "$ENV_FILE"; then
        echo 'overlays=wifi-ap6275p' >> "$ENV_FILE"
    elif ! grep -q 'wifi-ap6275p' "$ENV_FILE"; then
        sed -i 's/^overlays=\(.*\)$/overlays=\1 wifi-ap6275p/' "$ENV_FILE"
    fi
else
    log "WARN: $ENV_FILE not found; AP6275P overlay NOT applied"
fi

# ─── ethernet: link-local IPv4 fallback so Mac↔Pi direct cable works ───
# Without this, an ethernet interface that can't reach a DHCP server
# stays IPv4-less. NetworkManager (the default network manager on
# Ubuntu Jammy server with our packages) honours connection.autoconnect
# = ipv4.method=auto by default. Add a fallback: link-local.
log "installing ethernet link-local fallback connection"
install -m 0600 /dev/stdin /etc/NetworkManager/system-connections/sorteros-eth-fallback.nmconnection <<'EOF'
[connection]
id=sorteros-eth-fallback
type=ethernet
autoconnect=true
autoconnect-priority=-100
interface-name=

[ethernet]

[ipv4]
method=auto
# If DHCP fails, NM falls back to IPv4LL (169.254/16) thanks to
# may-fail=true on this connection's ipv4 block.
may-fail=true
dhcp-timeout=15

[ipv6]
method=auto
may-fail=true

[proxy]
EOF

# Also make sure avahi-daemon is enabled so the Pi advertises
# itself as <hostname>.local on whatever IP it ends up with.
systemctl enable avahi-daemon 2>/dev/null || true

# ─── dev/bring-up fallback Wi-Fi: Spencer's iPhone hotspot ───
# Until the cloud-init/Imager Wi-Fi customization path is reworked
# (FAT-first partitioning, v2.6 territory), bake a known NM connection
# so a freshly flashed card has *something* to associate with for
# initial Tailscale registration. NEVER ship in a customer image; it
# carries Spencer's PSK in plaintext.
# Important: the SSID uses U+2019 (right single quotation mark), not
# an ASCII apostrophe — phones with smart-quote names get this from
# iOS. NM matches SSID byte-for-byte, so the file must contain the
# UTF-8 bytes E2 80 99.
log "installing fallback Wi-Fi connection (Spencer's iPhone)"
python3 - <<'PYEOF'
import os, pathlib
ssid = "Spencer’s iPhone"
content = f"""[connection]
id=spencer-hotspot
type=wifi
autoconnect=true
autoconnect-priority=-200

[wifi]
ssid={ssid}
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
psk=hhhhhhhh

[ipv4]
method=auto

[ipv6]
method=ignore
"""
p = pathlib.Path("/etc/NetworkManager/system-connections/spencer-hotspot.nmconnection")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(content, encoding="utf-8")
os.chmod(p, 0o600)
PYEOF

# ─── optional: bake in a Tailscale auth-key for auto-join on first boot ───
# Reads TS_AUTH_KEY / TS_TAGS / TS_HOSTNAME from the chroot environment
# (extend.sh forwards them). If TS_AUTH_KEY is unset, this block no-ops.
if [[ -n "${TS_AUTH_KEY:-}" ]]; then
    log "TAILSCALE_AUTH_KEY present — wiring auto-join on first boot"
    mkdir -p /etc/sorteros /var/lib/sorteros
    install -m 0600 /dev/null /etc/sorteros/tailscale.env
    {
        echo "TAILSCALE_AUTH_KEY=${TS_AUTH_KEY}"
        echo "TAILSCALE_TAGS=${TS_TAGS:-tag:sorter}"
        [[ -n "${TS_HOSTNAME:-}" ]] && echo "TAILSCALE_HOSTNAME=${TS_HOSTNAME}"
    } >> /etc/sorteros/tailscale.env

    install -m 0755 /dev/stdin /usr/local/sbin/sorteros-tailscale-up.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
STAMP=/var/lib/sorteros/tailscale-up-done
[[ -f $STAMP ]] && exit 0
[[ -n "${TAILSCALE_AUTH_KEY:-}" ]] || { echo "no TAILSCALE_AUTH_KEY in env"; exit 0; }
HOST="${TAILSCALE_HOSTNAME:-sorter-$(cat /etc/hostname 2>/dev/null || echo unknown)}"
TAGS="${TAILSCALE_TAGS:-tag:sorter}"
systemctl enable --now tailscaled
for _ in 1 2 3 4 5 6 7 8 9 10; do
    [[ -S /var/run/tailscale/tailscaled.sock ]] && break
    sleep 1
done
tailscale up \
    --auth-key="$TAILSCALE_AUTH_KEY" \
    --hostname="$HOST" \
    --advertise-tags="$TAGS" \
    --ssh \
    --reset \
    --accept-dns=false
mkdir -p "$(dirname "$STAMP")"
touch "$STAMP"
sed -i '/^TAILSCALE_AUTH_KEY=/d' /etc/sorteros/tailscale.env
EOF

    install -m 0644 /dev/stdin /etc/systemd/system/sorteros-tailscale-up.service <<'EOF'
[Unit]
Description=SorterOS — register this node on Tailscale (first boot only)
After=network-online.target tailscaled.service
Wants=network-online.target
ConditionPathExists=/etc/sorteros/tailscale.env
ConditionPathExists=!/var/lib/sorteros/tailscale-up-done

[Service]
Type=oneshot
EnvironmentFile=/etc/sorteros/tailscale.env
ExecStart=/usr/local/sbin/sorteros-tailscale-up.sh
RemainAfterExit=yes
Restart=on-failure
RestartSec=10s
StartLimitBurst=5
StartLimitIntervalSec=120s

[Install]
WantedBy=multi-user.target
EOF
    systemctl enable sorteros-tailscale-up.service
fi

# ─── optional: swap the baked-in repo checkout to a different branch ───
# extend.sh passes its --branch arg into the chroot as $EXTEND_BRANCH.
# If set, we `git fetch + checkout + pull` inside the orangepi user's
# clone. Useful for shipping in-flight feature-branch work without a
# full rebuild from base.
if [[ -n "${EXTEND_BRANCH:-}" && -d /home/orangepi/sorter-v2/.git ]]; then
    log "switching sorter-v2 checkout to branch: $EXTEND_BRANCH"
    su - orangepi -c "cd ~/sorter-v2 && git fetch --depth=1 origin '$EXTEND_BRANCH' && git checkout -B '$EXTEND_BRANCH' FETCH_HEAD" || \
        log "WARN: branch switch to $EXTEND_BRANCH failed; image keeps the inherited checkout"
fi

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

log "running extend-provision inside chroot (branch swap: ${SORTER_BRANCH:-none}, TAILSCALE_AUTH_KEY=${TAILSCALE_AUTH_KEY:+<set>})"
chroot "$MNT" /usr/bin/env \
    "EXTEND_BRANCH=$SORTER_BRANCH" \
    "TS_AUTH_KEY=${TAILSCALE_AUTH_KEY:-}" \
    "TS_TAGS=${TAILSCALE_TAGS:-}" \
    "TS_HOSTNAME=${TAILSCALE_HOSTNAME:-}" \
    /tmp/extend-provision.sh
rm -f "$MNT/tmp/extend-provision.sh"

# v2.5: no FAT partition to populate.

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
