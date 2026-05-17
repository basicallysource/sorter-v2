#!/usr/bin/env bash
# Runs INSIDE the chroot. Architecture is aarch64; executed via
# qemu-user-static when the build host is x86_64.
#
# Idempotent. Re-running on an already-provisioned rootfs is safe.
#
# Scope notes: this script installs the toolchain and clones the repo.
# It does NOT run `uv sync` or `pnpm install` — those are deferred to
# `sorteros-firstboot.service` because (a) building PyTorch wheels under
# qemu-user emulation is glacial and (b) the heavy node_modules + venv
# would balloon the shipped image. They run on real hardware first boot.

set -euo pipefail

log() { echo "[provision $(date -u +%H:%M:%S)] $*"; }

export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8

# DEBIAN_FRONTEND=noninteractive alone does NOT silence dpkg conffile
# prompts; the Orange Pi base image ships hand-edited /etc/pulse/client.conf
# (and probably others), and the package install hangs on
# "install maintainer's version / keep yours" without these flags.
# --force-confold = keep modified file, --force-confdef = take default for
# untouched conflicts. Set via env so child apt/dpkg invocations inherit.
APT_OPTS=(
    -o Dpkg::Options::=--force-confdef
    -o Dpkg::Options::=--force-confold
    -y
)
APT_INSTALL=(apt-get install "${APT_OPTS[@]}" --no-install-recommends)

if [[ "$(stat -c %d:%i /)" == "$(stat -c %d:%i /proc/1/root/. 2>/dev/null || echo "")" ]]; then
    echo "refusing to provision: does not look like a chroot" >&2
    exit 1
fi

log "arch: $(uname -m); release: $(cat /etc/os-release | sed -n '1,2p' | tr '\n' ' ')"

# ─── apt: union of install.sh + audited dev-Pi packages ───
log "apt update"
apt-get update -y

log "apt install base packages"
"${APT_INSTALL[@]}" \
    ca-certificates curl wget gnupg \
    git git-lfs \
    build-essential pkg-config \
    python3 python3-pip python3-venv \
    libgl1 libglib2.0-0 \
    ffmpeg v4l-utils usbutils i2c-tools \
    lsof \
    udev \
    avahi-daemon \
    cloud-guest-utils \
    zstd

# Defensive: if any package landed half-configured (e.g. a maintainer
# script's `systemctl daemon-reload` failed inside the chroot), fix up.
log "apt -f install (post-install cleanup)"
apt-get "${APT_OPTS[@]}" -f install || true
dpkg --configure -a || true

# ─── tailscale (installed but NOT enabled; user opts in post-flash) ───
log "installing tailscale (disabled at boot)"
curl -fsSL https://tailscale.com/install.sh | sh
systemctl disable tailscaled 2>/dev/null || true

# ─── node 20 + pnpm ───
log "installing node 20"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
"${APT_INSTALL[@]}" nodejs
npm install -g pnpm@latest

# ─── orangepi user ───
# The base server image's first-boot wizard would create a user
# interactively. For the SorterOS image we bake a non-interactive
# orangepi user (UID 1000) so the systemd units and repo paths line up
# with the dev Pi conventions. Password is "orangepi" (matches Orange
# Pi's default), users are expected to change it.
if ! id orangepi >/dev/null 2>&1; then
    log "creating orangepi user (uid 1000)"
    useradd -m -u 1000 -s /bin/bash -G sudo,video,audio,dialout,plugdev,tty,disk,input,netdev,users,systemd-journal orangepi
    echo 'orangepi:orangepi' | chpasswd
fi
# Skip Orange Pi's interactive first-run wizard since we already have
# the orangepi user.
rm -f /root/.not_logged_in_yet 2>/dev/null || true

# ─── uv (installed as orangepi user under ~/.local/bin, matching dev Pi) ───
log "installing uv for orangepi"
su - orangepi -c 'curl -fsSL https://astral.sh/uv/install.sh | sh -s -- --no-modify-path'
# also symlink to /usr/local/bin so root and non-interactive shells find it
ln -sf /home/orangepi/.local/bin/uv /usr/local/bin/uv

# ─── sorter-v2 checkout ───
# Branch is controlled by SORTER_BRANCH env var (default: main). build.sh
# forwards its --branch flag here. Set to a feature branch to bake
# in-progress work into a test image, e.g.
#   SORTER_BRANCH=spencer/rev-02-distribution-board-03
SORTER_BRANCH="${SORTER_BRANCH:-main}"
log "cloning sorter-v2 (branch: $SORTER_BRANCH)"
su - orangepi -c "if [[ ! -d ~/sorter-v2 ]]; then git clone --depth=1 -b '$SORTER_BRANCH' https://github.com/basicallysource/sorter-v2.git ~/sorter-v2; fi"

# ─── overlay local sorteros/ source on top of the clone ───
# build.sh copies the host's software/sorteros/ tree (minus build/) into
# /tmp/sorteros-src/. We layer it on top so the image carries the current
# in-progress sorteros work even if it isn't merged to main yet.
if [[ -d /tmp/sorteros-src ]]; then
    log "overlaying local sorteros/ source from /tmp/sorteros-src"
    mkdir -p /home/orangepi/sorter-v2/software/sorteros
    cp -a /tmp/sorteros-src/. /home/orangepi/sorter-v2/software/sorteros/
fi

# ─── udev rule for the Picos (vendor 2e8a) ───
log "installing 99-sorter-pico.rules"
install -m 0644 /home/orangepi/sorter-v2/software/systemd/99-sorter-pico.rules \
    /etc/udev/rules.d/99-sorter-pico.rules

# ─── sorter systemd units (rendered from the repo's templates) ───
log "installing sorter-backend / sorter-ui systemd units"
SOFTWARE_DIR=/home/orangepi/sorter-v2/software
UV_BIN=/home/orangepi/.local/bin/uv
PNPM_BIN=$(command -v pnpm)
for unit in lego-sorter-backend.service lego-sorter-ui.service; do
    sed -e "s|__USER__|orangepi|g" \
        -e "s|__SOFTWARE_DIR__|${SOFTWARE_DIR}|g" \
        -e "s|__UV_BIN__|${UV_BIN}|g" \
        -e "s|__PNPM_BIN__|${PNPM_BIN}|g" \
        "${SOFTWARE_DIR}/systemd/${unit}" > "/etc/systemd/system/${unit}"
done
# Enable so they start at boot. They will fail until first-boot
# completes uv sync + pnpm install — that's expected and self-resolves.
systemctl enable lego-sorter-backend.service lego-sorter-ui.service

# ─── sorteros first-boot service ───
log "installing sorteros-firstboot.service"
install -m 0755 "${SOFTWARE_DIR}/sorteros/firstboot.sh" \
    /usr/local/sbin/sorteros-firstboot.sh
install -m 0644 "${SOFTWARE_DIR}/sorteros/sorteros-firstboot.service" \
    /etc/systemd/system/sorteros-firstboot.service
systemctl enable sorteros-firstboot.service

# ─── swap config (file is recreated by firstboot) ───
if ! grep -q "^/swapfile" /etc/fstab; then
    log "adding /swapfile to fstab"
    echo "/swapfile none swap sw,pri=-2 0 0" >> /etc/fstab
fi

# ─── systemd watchdog tweaks (matches dev Pi) ───
log "configuring systemd watchdog"
sed -i \
    -e 's/^#*RuntimeWatchdogSec=.*/RuntimeWatchdogSec=30s/' \
    -e 's/^#*RebootWatchdogSec=.*/RebootWatchdogSec=2min/' \
    /etc/systemd/system.conf

# ─── enable ssh ───
systemctl enable ssh 2>/dev/null || systemctl enable sshd 2>/dev/null || true

# ─── clean apt caches + uv cache to keep image small ───
log "cleaning caches"
apt-get clean
rm -rf /var/lib/apt/lists/*
rm -rf /home/orangepi/.cache/uv /root/.cache/uv 2>/dev/null || true

# ─── fix ownership of /home/orangepi just in case ───
chown -R 1000:1000 /home/orangepi

log "provision done"
