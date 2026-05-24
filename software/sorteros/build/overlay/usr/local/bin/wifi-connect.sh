#!/bin/bash
BACKUP_DIR="/var/lib/sorteros/wifi-backups"
NM_DIR="/etc/NetworkManager/system-connections"
LOG_FILE="/var/log/sorteros-wifi.log"
DELAY=30

log() {
    logger -t wifi-connect "$1"
    echo "$(date -Iseconds) [wifi-connect] $1" >> "$LOG_FILE"
}

log "starting — waiting ${DELAY}s to observe whether NetworkManager auto-reconnects on its own"
sleep $DELAY

if nmcli -t -f STATE general 2>/dev/null | grep -q "^connected$"; then
    log "connected after ${DELAY}s — NM auto-reconnected without intervention"
    exit 0
fi

log "not connected after ${DELAY}s — NM did NOT auto-reconnect, intervening"

shopt -s nullglob
backups=("$BACKUP_DIR"/*.nmconnection)
if [ ${#backups[@]} -eq 0 ]; then
    log "no backup profiles found — cannot force reconnect"
    exit 1
fi

nmcli dev wifi rescan 2>/dev/null || true
sleep 3
available=$(nmcli -t -f SSID dev wifi list 2>/dev/null | sort -u)
log "visible SSIDs: $(echo "$available" | tr '\n' ' ' | sed 's/ $//')"

for backup in "${backups[@]}"; do
    ssid=$(grep "^ssid=" "$backup" | cut -d= -f2-)
    [ -z "$ssid" ] && continue

    if echo "$available" | grep -qxF "$ssid"; then
        psk=$(grep "^psk=" "$backup" | cut -d= -f2-)
        if [ -z "$psk" ]; then
            log "could not extract PSK from backup for '$ssid', skipping"
            continue
        fi
        # An abrupt power loss can corrupt the NM connection file mid-write, leaving
        # a stale UUID or garbled credentials that cause NM to reject the PSK even
        # when the stored password is correct. Using 'nmcli dev wifi connect' (rather
        # than 'nmcli con up') bypasses NM's cached failure state for the connection
        # UUID and forces a fresh association, which reliably recovers after a crash.
        log "attempting to connect to '$ssid'"
        nmcli con delete "$ssid" 2>/dev/null || true
        sleep 2
        result=$(nmcli dev wifi connect "$ssid" password "$psk" 2>&1)
        if [ $? -eq 0 ]; then
            log "successfully connected to '$ssid'"
            cp "$NM_DIR/${ssid}.nmconnection" "$backup" 2>/dev/null || true
            chmod 600 "$backup" 2>/dev/null || true
            exit 0
        fi
        log "failed to connect to '$ssid': $result"
    else
        log "network '$ssid' not in range, skipping"
    fi
done

log "could not connect to any known backup network"
exit 1
