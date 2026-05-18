#!/usr/bin/env bash
# Runs inside the chroot via `chroot <rootfs> /tmp/chroot_apt.sh`.
# Installs the v3 apt delta on top of the Orange Pi base.
# Kept tiny on purpose — every package here is build time and image bytes.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8
APT_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold -y)

log() { echo "[chroot_apt $(date -u +%H:%M:%S)] $*"; }

if [[ ! -s /etc/resolv.conf ]]; then
    echo "nameserver 1.1.1.1" > /etc/resolv.conf
fi

log "apt update"
apt-get update -y

# Node 22 via NodeSource (pnpm@latest requires >=22.13).
if ! node --version 2>/dev/null | grep -q '^v22'; then
    log "installing Node 22"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install "${APT_OPTS[@]}" nodejs
    npm install -g pnpm@latest
fi

# Core v3 deltas: NetworkManager (Wi-Fi client + hotspot mode) and python+fastapi
# for the captive portal app. We use NM's built-in hotspot for the AP, so no
# bare hostapd / dnsmasq required. Keep python-fastapi system-installed so the
# AP service doesn't need a venv — it runs before firstboot finishes.
log "installing core packages"
apt-get install "${APT_OPTS[@]}" \
    network-manager \
    python3-pip \
    python3-fastapi \
    python3-uvicorn \
    python3-pydantic \
    python3-tomli

# Tailscale install is deferred to firstboot (sorteros-firstboot.py
# stage_install_tailscale): the base image's ext4 is sized for an 8 GB
# SD card and runs out of space if we bake in tailscale + node22 + the
# AP captive-portal deps. After growfs the rootfs has room, and
# tailscale-install can run idempotently on first boot when internet
# is available.

log "cleaning apt caches"
apt-get clean
rm -rf /var/lib/apt/lists/*

# Enable the v3 services (they're installed by the overlay step).
log "enabling sorteros-firstboot + sorteros-ap"
systemctl enable sorteros-firstboot.service || true
systemctl enable sorteros-ap.service || true

# NM pulls in dnsmasq as a dependency for hotspot mode, but systemd-resolved
# already owns port 53. Mask it so it never starts and pollutes the boot log.
systemctl mask dnsmasq.service || true

# Ensure /root/.ssh exists so root SSH key auth works out of the box.
mkdir -p /root/.ssh
chmod 700 /root/.ssh

log "done"
