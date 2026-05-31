#!/usr/bin/env bash
# Runs inside the chroot via `chroot <rootfs> /tmp/chroot_apt.sh`.
# Installs the v3 apt delta on top of the Orange Pi base.
# Kept tiny on purpose — every package here is build time and image bytes.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8
APT_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold -y)

log() { echo "[chroot_apt $(date -u +%H:%M:%S)] $*"; }

# resolv.conf is written by build.py from the host side before entering
# the chroot, so DNS is already working when we get here.

log "apt update"
apt-get update -y

# Node 22 via NodeSource (pnpm@latest requires >=22.13).
if ! node --version 2>/dev/null | grep -q '^v22'; then
    log "installing Node 22"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install "${APT_OPTS[@]}" nodejs
    npm install -g pnpm@latest
fi

log "installing core packages"
apt-get install "${APT_OPTS[@]}" \
    network-manager \
    dnsmasq-base \
    python3-pip \
    python3-tomli \
    libgl1 libglib2.0-0 \
    v4l-utils \
    git-lfs \
    cloud-guest-utils \
    figlet \
    systemd-timesyncd \
    qrencode

log "installing sorteros-portal python deps"
# Onboarding portal runs before the repo is cloned and before uv pulls the
# backend's venv — needs its own system-wide install of fastapi+uvicorn+
# pydantic. They land in /usr/local/lib/python3.* so `python3 portal.py`
# works straight from the overlay'd /usr/local/sbin/.
python3 -m pip install --no-cache-dir --break-system-packages \
    fastapi==0.115.4 \
    'uvicorn[standard]==0.32.0' \
    pydantic==2.9.2 \
    cryptography==43.0.3 || \
    python3 -m pip install --no-cache-dir \
        fastapi==0.115.4 \
        'uvicorn[standard]==0.32.0' \
        pydantic==2.9.2 \
        cryptography==43.0.3

# Without an enabled NTP client the system boots with a stale RTC, TLS certs
# fail "not yet valid", and clone-repo/uv-sync/pnpm-install all bail with
# git exit 128. timedatectl reports "NTP not supported" until we enable this.
systemctl enable systemd-timesyncd.service || true

# Rockchip hardware multimedia stack. Required by the backend's HW JPEG decode
# path (software/sorter/backend/vision/gst_capture.py -> GStreamer mppjpegdec).
# Without it the backend silently falls back to CPU cv2.VideoCapture, which
# starves the CPU and tanks the WebRTC streams. The -dev/gir/cairo packages are
# build deps for PyGObject + pycairo, which `uv sync` builds from source on
# first boot (they are aarch64/linux-only deps in backend/pyproject.toml).
log "adding Rockchip multimedia PPA"
apt-get install "${APT_OPTS[@]}" software-properties-common
add-apt-repository -y ppa:liujianfeng1994/rockchip-multimedia
apt-get update -y

log "installing Rockchip multimedia + PyGObject build deps"
apt-get install "${APT_OPTS[@]}" \
    librockchip-mpp1 librockchip-mpp-dev librockchip-vpu0 \
    librga2 librga-dev \
    gstreamer1.0-rockchip1 gstreamer1.0-tools \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    rockchip-multimedia-config rockchip-mpp-demos \
    libgirepository1.0-dev libcairo2-dev gir1.2-glib-2.0 pkg-config

# Tailscale install is deferred to firstboot (sorteros-firstboot.py
# stage_install_tailscale): the base image's ext4 is sized for an 8 GB
# SD card. After growfs the rootfs has room, and tailscale-install can
# run idempotently on first boot when internet is available.

log "installing uv"
curl -fsSL https://astral.sh/uv/install.sh | env HOME=/root sh
# Symlink into /usr/local/bin so all users can invoke it.
ln -sf /root/.local/bin/uv /usr/local/bin/uv

log "cleaning apt caches"
apt-get clean
rm -rf /var/lib/apt/lists/*

# Enable the v3 services (they're installed by the overlay step).
log "enabling sorteros-firstboot"
systemctl enable sorteros-firstboot.service || true

log "enabling sorteros-onboarding (portal)"
systemctl enable sorteros-onboarding.service || true

# We install dnsmasq-base (the binary NetworkManager spawns for AP/shared
# mode — required by the onboarding captive portal). The standalone
# dnsmasq.service must never run: systemd-resolved owns port 53, and NM
# manages its own dnsmasq instance internally. dnsmasq-base ships no
# service unit, but mask defensively in case the full dnsmasq pkg sneaks in.
systemctl mask dnsmasq.service || true

# Ensure /root/.ssh exists so root SSH key auth works out of the box.
mkdir -p /root/.ssh
chmod 700 /root/.ssh

# plugdev group for udev Pico access (99-sorter-pico.rules baked in by overlay).
# orangepi user must be a member so the backend can open /dev/ttyACM*.
getent group plugdev >/dev/null || groupadd --system plugdev
usermod -aG plugdev orangepi || true

log "done"
