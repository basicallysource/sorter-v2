#!/usr/bin/env bash
# Top-level orchestrator for SorterOS onboarding.
#
# Started by sorteros-onboarding.service. Behavior:
#
#   1. If /var/lib/sorteros/wifi-configured exists  → exit 0 (skip onboarding).
#   2. Else: bring up the AP via sorteros-ap-up.sh, then start the portal
#      backend in --mode=ap (binds 10.42.0.1:80) and wait on it.
#   3. When portal exits cleanly (wifi-configured was created) → tear down the AP.
#
# The portal Python process is what actually writes the NM connection,
# associates with the chosen SSID, and touches the gate file — this script
# just brackets the lifecycle.

set -euo pipefail

GATE=/var/lib/sorteros/wifi-configured
LOG_TAG=sorteros-onboarding
SKIP_WHEN_ONLINE=${SORTEROS_ONBOARDING_SKIP_WHEN_ONLINE:-0}

log() { logger -t "$LOG_TAG" -- "$*"; echo "[$LOG_TAG] $*" >&2; }

if [[ -f "$GATE" ]]; then
    log "wifi already configured (${GATE} exists) — onboarding skipped"
    exit 0
fi

# Normally the AP still comes up when Ethernet/USB-LAN is present: the portal is
# the first-run Wi-Fi/identity handoff, not only a reachability fallback. Lab or
# Ethernet-only images can opt out explicitly.
if [[ "$SKIP_WHEN_ONLINE" =~ ^(1|true|yes)$ ]] && ip route show default 2>/dev/null | grep -q .; then
    log "default route present and SORTEROS_ONBOARDING_SKIP_WHEN_ONLINE=${SKIP_WHEN_ONLINE} — skipping AP onboarding"
    exit 0
fi

log "fresh boot — entering onboarding mode"

# Bring up the AP. Failures here are recoverable on next boot.
if ! /usr/local/sbin/sorteros-ap-up.sh; then
    log "ap-up failed; exiting so onboarding.service can restart"
    exit 1
fi

# Hand off to the portal. --mode=ap makes it call real nmcli.
log "starting sorteros-portal on 10.42.0.1:80"
/usr/bin/env python3 /usr/local/sbin/sorteros-portal.py \
    --mode ap --host 0.0.0.0 --port 80 --static-dir /var/www/portal &
PORTAL_PID=$!

cleanup() {
    log "shutdown — stopping portal pid=${PORTAL_PID}"
    kill -TERM "$PORTAL_PID" 2>/dev/null || true
    wait "$PORTAL_PID" 2>/dev/null || true
}
trap cleanup TERM INT

# Watch the gate file — once the portal touches it (after a successful WiFi
# associate), bring the AP down so the device is on the user's network.
while ! [[ -f "$GATE" ]]; do
    if ! kill -0 "$PORTAL_PID" 2>/dev/null; then
        log "portal process exited before wifi was configured — bailing"
        cleanup
        exit 1
    fi
    sleep 2
done

log "wifi configured — tearing down AP"
/usr/local/sbin/sorteros-ap-down.sh || true

# Stop the portal so port 80 frees up for firstboot's status page.
cleanup
log "onboarding complete"
