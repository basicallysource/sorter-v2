#!/bin/bash
BACKUP_DIR="/var/lib/sorteros/wifi-backups"
NM_DIR="/etc/NetworkManager/system-connections"
LOG_FILE="/var/log/sorteros-wifi.log"

log() {
    logger -t wifi-repair "$1"
    echo "$(date -Iseconds) [wifi-repair] $1" >> "$LOG_FILE"
}

mkdir -p "$BACKUP_DIR"

shopt -s nullglob
backups=("$BACKUP_DIR"/*.nmconnection)
if [ ${#backups[@]} -eq 0 ]; then
    log "no backup profiles found in $BACKUP_DIR — nothing to repair"
    exit 0
fi

for backup in "${backups[@]}"; do
    ssid=$(grep "^ssid=" "$backup" | cut -d= -f2-)
    [ -z "$ssid" ] && continue

    nm_profile="$NM_DIR/${ssid}.nmconnection"

    if [ ! -f "$nm_profile" ] || ! grep -qF "ssid=$ssid" "$nm_profile" 2>/dev/null; then
        log "profile for '$ssid' missing or corrupted — restoring from backup"
        cp "$backup" "$nm_profile"
        chmod 600 "$nm_profile"
        log "restored '$ssid'"
    else
        log "profile for '$ssid' is intact"
    fi
done
