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
    OUT="$OUT_DIR_DEFAULT/sorteros-v2.7-${TS}.img"
fi
mkdir -p "$(dirname "$OUT")"

log() { echo "[extend $(date +%H:%M:%S)] $*"; }

trap cleanup_chroot EXIT

# ─── 0. Clean out stale build artifacts before we need the disk ───
# Previous failed/succeeded builds leave behind large files. Delete any
# prior sorteros-v*.img and leftover *.ext4.bin temp files so we don't
# run out of disk mid-build. The .zst base image and named input are kept.
log "cleaning stale artifacts from $OUT_DIR_DEFAULT"
find "$OUT_DIR_DEFAULT" -maxdepth 1 \( -name 'sorteros-v*.img' -o -name '*.ext4.bin' \) \
    ! -name "$(basename "$IN")" -delete 2>/dev/null || true
log "disk free: $(df -h "$OUT_DIR_DEFAULT" | awk 'NR==2{print $4}') available"

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

# ─── v2.5 partition restructure: move ext4 to p2, put FAT at p1 ───
# v2.4 put FAT after ext4. Two problems on hardware:
#   (a) RPi Imager only writes customization into p1 — our p1 was
#       ext4, so user-data/network-config never landed in our FAT.
#       cloud-init then died with FileNotFoundError /boot/firmware/user-data.
#   (b) growpart can't extend p1 into p2's space; rootfs stuck at 8 GiB.
# Fix: FAT at p1, ext4 at p2. Then Imager finds the FAT (it's p1),
# and growpart on p2 can extend it into all the SD card's tail space.
#
# Layout target:
#   bytes 0..30 MiB         : bootloader (untouched — copied verbatim)
#   bytes 30..286 MiB       : FAT32 partition 1 (label `system-boot`)
#   bytes 286 MiB..end      : ext4 partition 2 (the rootfs we already have)

FAT_SIZE_MIB=256
P1_START_MIB=30           # where the original ext4 starts (orange pi base)
P2_START_MIB=$(( P1_START_MIB + FAT_SIZE_MIB ))

# Get the original ext4 partition extent (sectors → MiB). We trust that
# the input image has exactly one ext4 partition at p1.
LOOP_TMP=$(losetup --show -fP "$OUT")
ORIG_P1_END_S=$(parted -ms "$LOOP_TMP" unit s print | awk -F: '/^1:/ {gsub("s","",$3); print $3}')
losetup -d "$LOOP_TMP"
ORIG_EXT4_LEN_MIB=$(( (ORIG_P1_END_S - (P1_START_MIB*2048) + 1) * 512 / 1024 / 1024 ))
log "original ext4: ${ORIG_EXT4_LEN_MIB} MiB at offset ${P1_START_MIB} MiB"

# Grow the image to make room for the FAT partition.
log "growing image by ${FAT_SIZE_MIB} MiB for the new FAT at p1"
truncate -s +"${FAT_SIZE_MIB}M" "$OUT"

# Move ext4 forward by FAT_SIZE_MIB. Going via a temp file avoids
# overlapping read/write hazards.
TMP_EXT4="${OUT}.ext4.bin"
log "extracting ext4 partition data → $TMP_EXT4"
dd if="$OUT" of="$TMP_EXT4" bs=1M skip="$P1_START_MIB" count="$ORIG_EXT4_LEN_MIB" \
    conv=fsync status=progress
log "writing ext4 partition data back at offset ${P2_START_MIB} MiB"
dd if="$TMP_EXT4" of="$OUT" bs=1M seek="$P2_START_MIB" \
    conv=notrunc,fsync status=progress
rm -f "$TMP_EXT4"

# Wipe the old partition table and write the new one.
log "rewriting MBR partition table (FAT@p1, ext4@p2)"
LOOP=$(losetup --show -fP "$OUT")
# Zero-out the partition entries region only (preserve bootloader code 0..445)
dd if=/dev/zero of="$LOOP" bs=1 seek=446 count=64 conv=notrunc status=none
# Now write fresh entries with parted. Using MiB units throughout.
parted -s "$LOOP" mklabel msdos
parted -s "$LOOP" mkpart primary fat32 "${P1_START_MIB}MiB" "${P2_START_MIB}MiB"
parted -s "$LOOP" set 1 lba on
# `100%` = end of disk minus alignment slack; safer than computing MiB
parted -s "$LOOP" mkpart primary ext4 "${P2_START_MIB}MiB" 100%
partprobe "$LOOP" || true
sleep 1
losetup -d "$LOOP"
LOOP=$(losetup --show -fP "$OUT")
log "re-attached loop: $LOOP"

FAT_PART="${LOOP}p1"
ROOT_PART="${LOOP}p2"
[[ -b $FAT_PART  ]] || { echo "FAT partition missing"; lsblk "$LOOP"; exit 1; }
[[ -b $ROOT_PART ]] || { echo "ext4 partition missing"; lsblk "$LOOP"; exit 1; }

log "formatting $FAT_PART as FAT32 (label: system-boot)"
mkfs.vfat -F 32 -n system-boot "$FAT_PART"

log "fsck of moved ext4 partition (should be clean — byte-for-byte move)"
e2fsck -fy "$ROOT_PART" || true

# ─── 3. Chroot into the rootfs ───
log "mounting rootfs + bind mounts for chroot"
mount_chroot "$ROOT_PART"

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

log "upgrading to node 22 (pnpm@latest requires >=22.13)"
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install "${APT_OPTS[@]}" nodejs
npm install -g pnpm@latest

log "installing cloud-init"
apt-get install "${APT_OPTS[@]}" --no-install-recommends cloud-init

log "writing /etc/cloud/cloud.cfg.d/99-sorteros.cfg"
mkdir -p /etc/cloud/cloud.cfg.d
cat >/etc/cloud/cloud.cfg.d/99-sorteros.cfg <<'EOF'
datasource_list: [ NoCloud, None ]
datasource:
  NoCloud:
    seedfrom: /boot/firmware/
# Don't let cloud-init's network module overwrite NetworkManager.
# `sorteros-apply-network-config.service` translates Imager's seed.
network:
  config: disabled
# ssh_authkey_fingerprints fails on this platform (exits nonzero even
# though it prints correctly), causing cloud-final.service to show as
# failed. Disable it — fingerprints aren't needed at runtime.
ssh_authkey_fingerprints:
  enabled: false
EOF

log "creating /boot/firmware mountpoint + fstab entry"
mkdir -p /boot/firmware
if ! grep -q "^LABEL=system-boot" /etc/fstab; then
    echo "LABEL=system-boot  /boot/firmware  vfat  defaults,noatime,nofail  0  2" >> /etc/fstab
fi

# ─── apply-network-config: parse Imager's network-config and hand to nmcli ───
install -m 0755 /dev/stdin /usr/local/sbin/sorteros-apply-network-config.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
SEED=/boot/firmware/network-config
STAMP=/var/lib/sorteros/network-config-applied
mkdir -p "$(dirname "$STAMP")"
[[ -f $STAMP ]] && exit 0
[[ -f $SEED ]] || exit 0
# RPi Imager writes: access-points:\n  "SSID":\n    password: "psk"
# Extract the SSID key under access-points: and the password/psk value.
SSID=$(awk '/access-points:/{found=1; next} found && /:[[:space:]]*$/{gsub(/^[[:space:]"]+|"[[:space:]]*:.*$/, ""); print; exit}' "$SEED" || true)
PSK=$(awk '/password:|psk:/{gsub(/.*:[[:space:]"]*|"[[:space:]]*$/, ""); print; exit}' "$SEED" || true)
if [[ -n $SSID && -n $PSK ]] && command -v nmcli >/dev/null 2>&1; then
    nmcli device wifi connect "$SSID" password "$PSK" || true
fi
touch "$STAMP"
EOF
install -m 0644 /dev/stdin /etc/systemd/system/sorteros-apply-network-config.service <<'EOF'
[Unit]
Description=SorterOS — apply RPi Imager Wi-Fi customization on first boot
After=local-fs.target NetworkManager.service
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

# ─── growfs: extend ext4 (p2) into the SD card's unallocated tail ───
# Runs BEFORE cloud-init so cloud-init has full disk space.
install -m 0755 /dev/stdin /usr/local/sbin/sorteros-growfs.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
STAMP=/var/lib/sorteros/growfs-done
mkdir -p "$(dirname "$STAMP")"
[[ -f $STAMP ]] && exit 0
ROOT_DEV=$(findmnt -no SOURCE /)
ROOT_DISK=$(lsblk -no PKNAME "$ROOT_DEV" | head -1)
PART_NUM=$(echo "$ROOT_DEV" | grep -oE '[0-9]+$')
if [[ -n $ROOT_DISK && -n $PART_NUM ]]; then
    growpart "/dev/$ROOT_DISK" "$PART_NUM" || true
    resize2fs "$ROOT_DEV" || true
fi
touch "$STAMP"
EOF
install -m 0644 /dev/stdin /etc/systemd/system/sorteros-growfs.service <<'EOF'
[Unit]
Description=SorterOS — grow the root ext4 to fill the card (first boot only)
DefaultDependencies=no
After=local-fs.target
Before=cloud-init-local.service cloud-init.service sysinit.target
ConditionPathExists=!/var/lib/sorteros/growfs-done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sorteros-growfs.sh
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
EOF
systemctl enable sorteros-growfs.service

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

# ─── Spencer's iPhone hotspot: ALWAYS-ON fallback Wi-Fi ───
# "100% accessible" requirement — if Imager's customization is missing
# or wrong, or the user-picked SSID isn't in range, NM must still find
# *something* that gets the Pi onto the internet so Tailscale can
# register. The iPhone hotspot covers that. autoconnect-priority=200
# is high enough to beat NM's defaults but Imager-injected SSIDs (which
# nmcli writes with no priority specified, default 0) won't outrank it
# unless they happen to be in range. The expectation: iPhone in pocket
# at all times during dev → Pi associates with it, Tailscale comes up.
# NEVER ship in a customer image; this carries the PSK in plaintext.
# SSID uses U+2019 (right single quote), not ASCII apostrophe — NM
# matches the SSID byte-for-byte against what iOS broadcasts.
log "installing fallback Wi-Fi (Spencer's iPhone, autoconnect-priority=200)"
python3 - <<'PYEOF'
import os, pathlib
ssid = "Spencer’s iPhone"
content = f"""[connection]
id=spencer-hotspot
type=wifi
autoconnect=true
autoconnect-priority=200
autoconnect-retries=0

[wifi]
ssid={ssid}
mode=infrastructure
hidden=false

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
    su - orangepi -c "cd ~/sorter-v2 && git clean -fd && git fetch --depth=1 origin '$EXTEND_BRANCH' && git checkout -B '$EXTEND_BRANCH' FETCH_HEAD" || \
        log "WARN: branch switch to $EXTEND_BRANCH failed; image keeps the inherited checkout"
fi

# ─── blank .env so lego-sorter-backend.service can load on first boot ───
# The backend's EnvironmentFile= hard-fails if the file is missing.
# A blank .env lets the service attempt to start; it will fail on missing
# required vars, but that's a restart-loop rather than a load error.
# The user populates this with real values after flashing.
ENV_PATH=/home/orangepi/sorter-v2/software/.env
if [[ ! -f "$ENV_PATH" ]]; then
    log "creating blank .env at $ENV_PATH"
    install -m 0600 -o 1000 -g 1000 /dev/null "$ENV_PATH"
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

# Note: growpart + resize2fs are handled by sorteros-growfs.service
# (runs Before=cloud-init-local.service so cloud-init has full disk).

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

# ─── Populate the FAT partition with cloud-init seed scaffolding ───
log "populating FAT partition with seed scaffolding"
FAT_MNT=$(mktemp -d)
mount "$FAT_PART" "$FAT_MNT"

# v2.6: copy /boot/ from the ext4 rootfs onto the FAT. u-boot scans
# the partition table in order and reads kernel + boot.scr from the
# first partition it finds them on. With FAT-at-p1 and an empty FAT,
# u-boot never found boot.scr/Image and silently bricked (no green
# LED). Mirror /boot/ to the FAT so u-boot finds everything on the
# bootable partition. The OS still keeps its own /boot/ on ext4 for
# kernel package upgrades; a future flash-kernel-style hook can re-
# sync to /boot/firmware (which is this FAT) on kernel updates.
log "copying ext4 /boot/ → FAT /boot/ (so u-boot finds the kernel)"
mkdir -p "$FAT_MNT/boot"
# FAT can't store symlinks OR hard links. /boot has both — versionless
# names like Image/uInitrd/dtb are symlinks to versioned files, and
# kernel-package post-install creates additional hard links between
# them. `cp -rL` recursively copies with symlinks dereferenced and
# DOESN'T try to preserve hard-link structure (which `cp -a` would).
# Result on the FAT: every name is a regular file. u-boot loads them
# directly. Trade-off: ~84 MB on ext4 becomes ~120 MB on FAT (links
# get duplicated as real files). Still fits in 256 MB.
cp -rL "$MNT/boot/." "$FAT_MNT/boot/"
sync

: > "$FAT_MNT/meta-data"
cat >"$FAT_MNT/README.txt" <<'EOF'
SorterOS boot partition.
RPi Imager writes user-data / network-config here for first-boot setup.
The /boot/ subdirectory holds the kernel, initrd, dtbs and boot.scr
that u-boot loads on power-on. Do not delete /boot/ — the Pi won't
boot without it.
EOF
cat >"$FAT_MNT/user-data.example" <<'EOF'
#cloud-config
# Rename to `user-data` to apply on next boot.
hostname: sorter
manage_etc_hosts: true
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
