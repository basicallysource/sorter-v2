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

# Core v3 deltas: hostapd + dnsmasq for the AP, NetworkManager for client mode.
log "installing core packages"
apt-get install "${APT_OPTS[@]}" \
    hostapd \
    dnsmasq \
    network-manager \
    python3-pip

# Tailscale binary (NOT auto-up; firstboot decides based on /etc/sorteros).
log "installing tailscale"
curl -fsSL https://tailscale.com/install.sh | sh

log "cleaning apt caches"
apt-get clean
rm -rf /var/lib/apt/lists/*

# Enable the v3 services (they're installed by the overlay step).
log "enabling sorteros-firstboot + sorteros-ap"
systemctl enable sorteros-firstboot.service || true
systemctl enable sorteros-ap.service || true

# Disable NM-managed wifi at boot — sorteros-ap decides whether to be in
# AP mode or client mode based on /etc/sorteros-config.toml.
log "done"
