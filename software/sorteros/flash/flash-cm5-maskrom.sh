#!/usr/bin/env bash
# Flash a SorterOS image onto the Orange Pi CM5 via Rockchip MaskROM.
# Defaults to the newest image in software/sorteros/build/out/.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
IMAGE=$(ls -t "${SCRIPT_DIR}/../build/out/"*.img 2>/dev/null | head -1 || true)
LOADER="${SCRIPT_DIR}/rkbin/rk3588_spl_loader_v1.16.113.bin"
READBACK="${SCRIPT_DIR}/flash-readback-first16m.img"
WAIT_SECONDS=0
NO_REBOOT=0

usage() {
	cat <<EOF
Usage: $0 [options]

Options:
  --image PATH        Image to flash.
  --loader PATH       RK3588 SPL loader for rkdeveloptool db.
  --readback PATH     First-16MiB readback file.
  --wait SECONDS      Wait up to SECONDS for MaskROM/Loader to appear.
  --no-reboot         Do not run 'rkdeveloptool rd' after verification.
  -h, --help          Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--image)
			IMAGE=$2
			shift 2
			;;
		--loader)
			LOADER=$2
			shift 2
			;;
		--readback)
			READBACK=$2
			shift 2
			;;
		--wait)
			WAIT_SECONDS=$2
			shift 2
			;;
		--no-reboot)
			NO_REBOOT=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unknown option: $1" >&2
			usage >&2
			exit 1
			;;
	esac
done

for tool in rkdeveloptool shasum dd; do
	if ! command -v "${tool}" >/dev/null 2>&1; then
		echo "Required tool not found: ${tool}" >&2
		exit 1
	fi
done

if [[ ! -f "${IMAGE}" ]]; then
	echo "Image not found: ${IMAGE}" >&2
	exit 1
fi

if [[ ! -f "${LOADER}" ]]; then
	echo "Loader not found: ${LOADER}" >&2
	exit 1
fi

maskrom_seen() {
	local out
	out=$(rkdeveloptool ld 2>&1 || true)
	printf '%s\n' "${out}" >&2
	[[ -n "${out}" && "${out}" != *"not found any devices"* ]]
}

deadline=$((SECONDS + WAIT_SECONDS))
until maskrom_seen; do
	if (( SECONDS >= deadline )); then
		echo "No Rockchip MaskROM/Loader device visible." >&2
		exit 1
	fi
	sleep 1
done

mkdir -p "$(dirname -- "${READBACK}")"
tmp_first16=$(mktemp "${TMPDIR:-/tmp}/sorteros-image-first16m.XXXXXX")
trap 'rm -f "${tmp_first16}"' EXIT

echo "[flash-cm5] image:  ${IMAGE}"
echo "[flash-cm5] loader: ${LOADER}"
shasum -a 256 "${IMAGE}"

echo "[flash-cm5] loading SPL"
rkdeveloptool db "${LOADER}"
sleep 2
rkdeveloptool rfi || true

echo "[flash-cm5] writing image"
rkdeveloptool wl 0x0 "${IMAGE}"

echo "[flash-cm5] reading first 16MiB back"
rkdeveloptool rl 0 32768 "${READBACK}"
dd if="${IMAGE}" of="${tmp_first16}" bs=1m count=16 2>/dev/null

image_first_hash=$(shasum -a 256 "${tmp_first16}" | awk '{print $1}')
readback_hash=$(shasum -a 256 "${READBACK}" | awk '{print $1}')
echo "[flash-cm5] image first16: ${image_first_hash}"
echo "[flash-cm5] readback:      ${readback_hash}"

if [[ "${image_first_hash}" != "${readback_hash}" ]]; then
	echo "Readback mismatch; leaving board in current mode for inspection." >&2
	exit 1
fi

echo "[flash-cm5] readback verified"

if [[ ${NO_REBOOT} -eq 0 ]]; then
	echo "[flash-cm5] rebooting board"
	rkdeveloptool rd || true
fi
