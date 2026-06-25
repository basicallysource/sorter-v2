#!/usr/bin/env bash
# Bring up the SorterOS onboarding access point on the first available Wi-Fi
# interface — idempotent.
#
# Called by sorteros-onboarding.service on boot when /var/lib/sorteros/wifi-configured
# is absent. Creates (or updates) an nmcli AP profile, ipv4-shared so NetworkManager
# spins up its own dnsmasq for DHCP + DNS. The DNS hijack lives in
# /etc/NetworkManager/dnsmasq-shared.d/sorteros-portal.conf (baked into the image).

set -euo pipefail

AP_CON=sorteros-ap
REQUESTED_IFACE=${SORTEROS_ONBOARDING_WIFI_IFACE:-}
GATEWAY=10.42.0.1/24
LOG_TAG=sorteros-ap-up

log() { logger -t "$LOG_TAG" -- "$*"; echo "[$LOG_TAG] $*" >&2; }

list_wifi_ifaces() {
    if command -v nmcli >/dev/null 2>&1; then
        nmcli -t -f DEVICE,TYPE dev status 2>/dev/null | awk -F: '$2 == "wifi" { print $1 }'
    fi

    for path in /sys/class/net/wlan* /sys/class/net/wl*; do
        [[ -e "$path" ]] || continue
        basename "$path"
    done
}

resolve_wifi_iface() {
    if [[ -n "$REQUESTED_IFACE" ]]; then
        echo "$REQUESTED_IFACE"
        return 0
    fi

    list_wifi_ifaces | awk 'NF && !seen[$0]++ { print; exit }'
}

# Wait briefly for NetworkManager to take charge of Wi-Fi — on cold boot the
# radio is usually settled by the time onboarding.service starts, but USB Wi-Fi
# and firmware loading can lag.
IFACE=""
for _ in $(seq 1 30); do
    IFACE=$(resolve_wifi_iface)
    if [[ -n "$IFACE" ]] && nmcli -t -f DEVICE,TYPE dev status | awk -F: -v dev="$IFACE" '$1 == dev && $2 == "wifi" { found = 1 } END { exit !found }'; then
        break
    fi
    sleep 1
done

if [[ -z "$IFACE" ]] || ! nmcli -t -f DEVICE,TYPE dev status | awk -F: -v dev="$IFACE" '$1 == dev && $2 == "wifi" { found = 1 } END { exit !found }'; then
    if [[ -n "$REQUESTED_IFACE" ]]; then
        log "requested Wi-Fi interface ${REQUESTED_IFACE} not present after 30s — bailing"
    else
        log "no NetworkManager Wi-Fi interface present after 30s — bailing"
    fi
    exit 1
fi

log "using Wi-Fi interface ${IFACE}"

# Derive SSID from the selected interface MAC so two adjacent devices in AP mode
# don't clash.
mac=$(cat /sys/class/net/${IFACE}/address 2>/dev/null || echo "00:00:00:00:00:00")
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
