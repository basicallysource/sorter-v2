#!/usr/bin/env bash
# Tear down the SorterOS onboarding AP after the portal has accepted credentials.
# Safe to run when the AP isn't up — `connection down/delete` no-op cleanly.

set -euo pipefail

AP_CON=sorteros-ap
LOG_TAG=sorteros-ap-down

log() { logger -t "$LOG_TAG" -- "$*"; echo "[$LOG_TAG] $*" >&2; }

nmcli connection down "$AP_CON" >/dev/null 2>&1 || true
nmcli connection delete "$AP_CON" >/dev/null 2>&1 || true

log "ap profile removed"
