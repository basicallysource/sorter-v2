#!/usr/bin/env bash
# Regenerate the Orange Pi CM5 Tablet DTB used by the SorterOS Armbian image.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DT_SRC="${SCRIPT_DIR}/dt-src/rk35xx-vendor-6.1"
KERNEL_TREE=${CM5_DTB_KERNEL_TREE:-}
OUT="${SCRIPT_DIR}/artifacts/rk3588s-orangepi-cm5-tablet.dtb"

usage() {
	cat <<EOF
Usage: $0 --kernel-tree PATH [--out PATH]

Options:
  --kernel-tree PATH  Armbian linux-rockchip checkout, branch rk-6.1-rkr5.1.
  --out PATH          Output DTB path.
  -h, --help          Show this help.

The expected kernel tree commit for the current Phase 0 image is:
  713542620f7c9c6287ef11487748e7bae13a63df
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--kernel-tree)
			KERNEL_TREE=$2
			shift 2
			;;
		--out)
			OUT=$2
			shift 2
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

if [[ -z "${KERNEL_TREE}" && -d /tmp/sorteros-linux-rockchip-rk61 ]]; then
	KERNEL_TREE=/tmp/sorteros-linux-rockchip-rk61
fi

if [[ -z "${KERNEL_TREE}" || ! -d "${KERNEL_TREE}" ]]; then
	echo "Kernel tree not found. Pass --kernel-tree or set CM5_DTB_KERNEL_TREE." >&2
	exit 1
fi

if [[ ! -f "${KERNEL_TREE}/arch/arm64/boot/dts/rockchip/rk3588s.dtsi" ]]; then
	echo "Kernel tree does not look like linux-rockchip rk-6.1-rkr5.1: ${KERNEL_TREE}" >&2
	exit 1
fi

if ! command -v cpp >/dev/null 2>&1; then
	echo "cpp not found." >&2
	exit 1
fi

if ! command -v dtc >/dev/null 2>&1; then
	echo "dtc not found. Install device-tree-compiler." >&2
	exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

work_dts="${tmp}/arch/arm64/boot/dts/rockchip"
mkdir -p "${work_dts}" "$(dirname -- "${OUT}")"
cp -a "${DT_SRC}/." "${work_dts}/"

cpp -nostdinc -undef -x assembler-with-cpp \
	-I "${KERNEL_TREE}/include" \
	-I "${KERNEL_TREE}/arch/arm64/boot/dts" \
	-I "${KERNEL_TREE}/arch/arm64/boot/dts/rockchip" \
	-I "${work_dts}" \
	"${work_dts}/rk3588s-orangepi-cm5-tablet.dts" \
	>"${tmp}/rk3588s-orangepi-cm5-tablet.pre.dts"

dtc -@ -I dts -O dtb \
	-o "${OUT}" \
	"${tmp}/rk3588s-orangepi-cm5-tablet.pre.dts"

sha256sum "${OUT}" 2>/dev/null || shasum -a 256 "${OUT}"
