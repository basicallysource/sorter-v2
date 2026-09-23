#!/usr/bin/env bash
# Bring up the SorterOS onboarding access point on the Wi-Fi device — idempotent.
#
# Called by sorteros-onboarding.service on boot when /var/lib/sorteros/wifi-configured
# is absent. Creates (or updates) an nmcli AP profile, ipv4-shared so NetworkManager
# spins up its own dnsmasq for DHCP + DNS. The DNS hijack lives in
# /etc/NetworkManager/dnsmasq-shared.d/sorteros-portal.conf (baked into the image).

set -euo pipefail

AP_CON=sorteros-ap
GATEWAY=10.42.0.1/24
LOG_TAG=sorteros-ap-up

log() { logger -t "$LOG_TAG" -- "$*"; echo "[$LOG_TAG] $*" >&2; }

# The first Wi-Fi device NetworkManager manages: wlan0 for the M.2 module,
# wlx<mac> for a USB adapter. On cold boot a USB adapter or late-loading
# firmware can lag, so give it a moment.
IFACE=""
for _ in $(seq 1 15); do
    IFACE=$(nmcli -t -f DEVICE,TYPE device 2>/dev/null | awk -F: '$2 == "wifi" { print $1; exit }')
    [ -n "$IFACE" ] && break
    sleep 1
done
if [ -z "$IFACE" ]; then
    log "no Wi-Fi device after 15s — bailing"
    exit 1
fi

# SSID from the device's MAC so two machines in setup mode don't clash.
mac=$(cat "/sys/class/net/${IFACE}/address" 2>/dev/null || echo "00:00:00:00:00:00")
suffix=$(echo "$mac" | tr -d ':' | tail -c 7 | tr 'a-f' 'A-F')
SSID="SorterOS-Setup-${suffix}"

# Tear down any stale instance of the AP profile so we always boot from a
# known shape (SSID may have changed if the MAC changed, e.g. swapped board).
if nmcli -t -f NAME connection show | grep -qx "$AP_CON"; then
    nmcli connection down "$AP_CON" >/dev/null 2>&1 || true
    nmcli connection delete "$AP_CON" >/dev/null 2>&1 || true
fi

log "creating AP connection profile ${AP_CON} ssid=${SSID}"
nmcli connection add \
    type wifi ifname "$IFACE" con-name "$AP_CON" \
    autoconnect no ssid "$SSID" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel 6 \
    ipv4.method shared ipv4.addresses "$GATEWAY" \
    ipv6.method ignore

log "bringing AP up"
nmcli connection up "$AP_CON"

log "ap online — ssid=${SSID} gw=${GATEWAY%%/*}"
