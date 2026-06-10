#!/usr/bin/env bash
# Runs inside the chroot via `chroot <rootfs> /tmp/chroot_apt.sh`.
# Installs the v3 apt delta on top of the Orange Pi base.
# Kept tiny on purpose — every package here is build time and image bytes.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8
APT_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold -y)

log() { echo "[chroot_apt $(date -u +%H:%M:%S)] $*"; }

set_login_password() {
    local user=$1
    local password=$2
    [ -n "${password}" ] || return 0
    printf '%s:%s\n' "${user}" "${password}" | chpasswd
}

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
    openssh-server \
    avahi-daemon \
    sudo \
    dnsmasq-base \
    python3-pip \
    python3-dev \
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

log "configuring first-boot networking and SSH access"
mkdir -p /etc/netplan /etc/ssh/sshd_config.d
chmod +x /usr/local/sbin/sorteros-bootstrap-users.sh || true
chmod +x /usr/local/sbin/sorteros-usb-gadget.sh || true
find /etc/netplan -maxdepth 1 -type f \( -name '*.yaml' -o -name '*.yml' \) -delete
cat >/etc/netplan/99-sorteros-networkmanager.yaml <<'EOF'
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    all-eth-interfaces:
      match:
        name: "e*"
      dhcp4: true
      dhcp6: true
      optional: true
    all-lan-interfaces:
      match:
        name: "lan[0-9]*"
      dhcp4: true
      dhcp6: true
      optional: true
    all-wan-interfaces:
      match:
        name: "wan[0-9]*"
      dhcp4: true
      dhcp6: true
      optional: true
EOF
cat >/etc/ssh/sshd_config.d/90-sorteros.conf <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin prohibit-password
EOF
ssh-keygen -A || true
systemctl enable NetworkManager.service || true
systemctl enable sorteros-usb-gadget.service || true
systemctl enable ssh.service || systemctl enable sshd.service || true
systemctl enable avahi-daemon.service || true
systemctl enable sorteros-bootstrap-users.service || true
systemctl disable systemd-networkd.service systemd-networkd-wait-online.service || true

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
    libv4l-0 libv4l-dev libv4l-rkmpp \
    ffmpeg \
    gstreamer1.0-rockchip1 gstreamer1.0-tools \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    rockchip-multimedia-config rockchip-mpp-demos \
    python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
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

if [ -f /usr/lib/librknnrt.so ]; then
    log "refreshing linker cache for RKNN runtime"
    ldconfig
fi

# Enable the v3 services (they're installed by the overlay step).
log "enabling sorteros-firstboot"
systemctl enable sorteros-firstboot.service || true

log "enabling sorteros-onboarding (portal)"
systemctl enable sorteros-onboarding.service || true

log "enabling sorteros-performance-governor"
systemctl enable sorteros-performance-governor.service || true

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
# video/render groups for Rockchip MPP/RGA/DRM access. The backend should not
# need root just to use the camera transport hardware path.
# orangepi user must be a member so the backend can open /dev/ttyACM* and video
# accelerator nodes after first boot.
getent group plugdev >/dev/null || groupadd --system plugdev
getent group video >/dev/null || groupadd --system video
getent group render >/dev/null || groupadd --system render

if ! id -u orangepi >/dev/null 2>&1; then
    log "creating orangepi user"
    useradd --create-home --shell /bin/bash --groups sudo,plugdev,video,render orangepi
fi
usermod -aG sudo,plugdev,video,render orangepi
install -d -m 0750 -o orangepi -g orangepi /home/orangepi
echo "orangepi ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-orangepi
chmod 0440 /etc/sudoers.d/90-orangepi

log "setting local console passwords"
SORTEROS_DEFAULT_PASSWORD=${SORTEROS_DEFAULT_PASSWORD:-sorteros}
set_login_password root "${SORTEROS_ROOT_PASSWORD:-${SORTEROS_DEFAULT_PASSWORD}}"
set_login_password orangepi "${SORTEROS_ORANGEPI_PASSWORD:-${SORTEROS_DEFAULT_PASSWORD}}"

log "disabling interactive Armbian first-login wizard"
rm -f /root/.not_logged_in_yet
rm -f /etc/profile.d/armbian-check-first-login.sh
rm -f /etc/profile.d/armbian-check-first-login-reboot.sh
systemctl disable armbian-firstrun.service >/dev/null 2>&1 || true

if [ -s /etc/sorteros/bootstrap_authorized_keys ]; then
    log "installing bootstrap SSH authorized keys"

    install -d -m 0700 -o root -g root /root/.ssh
    cat /etc/sorteros/bootstrap_authorized_keys >>/root/.ssh/authorized_keys
    sort -u /root/.ssh/authorized_keys -o /root/.ssh/authorized_keys
    chmod 0600 /root/.ssh/authorized_keys
    chown root:root /root/.ssh/authorized_keys

    install -d -m 0700 -o orangepi -g orangepi /home/orangepi/.ssh
    cat /etc/sorteros/bootstrap_authorized_keys >>/home/orangepi/.ssh/authorized_keys
    sort -u /home/orangepi/.ssh/authorized_keys -o /home/orangepi/.ssh/authorized_keys
    chmod 0600 /home/orangepi/.ssh/authorized_keys
    chown orangepi:orangepi /home/orangepi/.ssh/authorized_keys
fi

log "done"
