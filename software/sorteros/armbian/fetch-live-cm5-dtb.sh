#!/usr/bin/env bash
# Copy the currently booted Orange Pi CM5 tablet DTB into the Phase 0 artifacts.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REMOTE=${1:-${SORTEROS_REMOTE:-}}
REMOTE_DTB=${REMOTE_DTB:-/boot/dtb/rockchip/rk3588s-orangepi-cm5-tablet.dtb}
OUT="${SCRIPT_DIR}/artifacts/rk3588s-orangepi-cm5-tablet.dtb"

if [[ -z "${REMOTE}" ]]; then
	echo "usage: $0 <user@host>" >&2
	echo "or set SORTEROS_REMOTE=<user@host>" >&2
	exit 2
fi

mkdir -p "${SCRIPT_DIR}/artifacts"

echo "[sorteros-armbian] inspecting ${REMOTE}"
ssh "${REMOTE}" 'set -e
printf "model="
tr -d "\0" </proc/device-tree/model
printf "\ncompatible="
tr "\0" " " </proc/device-tree/compatible
printf "\nkernel="
uname -r
printf "\n"
test -f /boot/dtb/rockchip/rk3588s-orangepi-cm5-tablet.dtb
'

echo "[sorteros-armbian] copying ${REMOTE}:${REMOTE_DTB} -> ${OUT}"
scp "${REMOTE}:${REMOTE_DTB}" "${OUT}"

echo "[sorteros-armbian] wrote ${OUT}"
sha256sum "${OUT}" || shasum -a 256 "${OUT}"
