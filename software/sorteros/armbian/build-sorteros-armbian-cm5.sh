#!/usr/bin/env bash
# Prepare Armbian userpatches and build the SorterOS CM5 vendor-6.1 image.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../../.." && pwd)
ARMBIAN_DIR=${ARMBIAN_BUILD_DIR:-${HOME}/Workspace/armbian-build-sorteros}
BOARD=orangepi-cm5-sorter
RELEASE=noble
BRANCH=vendor
SORTEROS_BRANCH=${SORTEROS_BRANCH:-sorthive}
FORCE_USERPATCHES=0
PREPARE_ONLY=0

usage() {
	cat <<EOF
Usage: $0 [options] [-- extra compile.sh args]

Options:
  --armbian-dir PATH       Armbian build checkout (default: ~/Workspace/armbian-build-sorteros)
  --board NAME             Armbian BOARD (default: orangepi-cm5-sorter)
  --release NAME           Armbian RELEASE (default: noble)
  --branch NAME            Armbian BRANCH (default: vendor)
  --sorteros-branch NAME   sorter-v2 branch encoded for firstboot (default: sorthive)
  --force-userpatches      Replace existing armbian/build/userpatches
  --prepare-only           Prepare userpatches, then stop before compile.sh
  -h, --help               Show this help
EOF
}

EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
	case "$1" in
		--armbian-dir)
			ARMBIAN_DIR=$2
			shift 2
			;;
		--board)
			BOARD=$2
			shift 2
			;;
		--release)
			RELEASE=$2
			shift 2
			;;
		--branch)
			BRANCH=$2
			shift 2
			;;
		--sorteros-branch)
			SORTEROS_BRANCH=$2
			shift 2
			;;
		--force-userpatches)
			FORCE_USERPATCHES=1
			shift
			;;
		--prepare-only)
			PREPARE_ONLY=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		--)
			shift
			EXTRA_ARGS+=("$@")
			break
			;;
		*)
			EXTRA_ARGS+=("$1")
			shift
			;;
	esac
done

if [[ ! -x "${ARMBIAN_DIR}/compile.sh" ]]; then
	echo "Armbian compile.sh not found: ${ARMBIAN_DIR}/compile.sh" >&2
	echo "Clone https://github.com/armbian/build or set ARMBIAN_BUILD_DIR." >&2
	exit 1
fi

USERPATCHES="${ARMBIAN_DIR}/userpatches"
if [[ -e "${USERPATCHES}" && ${FORCE_USERPATCHES} -ne 1 ]]; then
	echo "${USERPATCHES} already exists." >&2
	echo "Re-run with --force-userpatches to replace it with the SorterOS Phase 0 userpatches." >&2
	exit 1
fi

echo "[sorteros-armbian] preparing userpatches in ${USERPATCHES}"
rm -rf "${USERPATCHES}"
mkdir -p "${USERPATCHES}"
rsync -a "${SCRIPT_DIR}/userpatches/" "${USERPATCHES}/"
mkdir -p "${USERPATCHES}/overlay"
rsync -a "${REPO_ROOT}/software/sorteros/build/overlay/" "${USERPATCHES}/overlay/"

mkdir -p "${USERPATCHES}/overlay/tmp" "${USERPATCHES}/overlay/etc/sorteros"
cp "${REPO_ROOT}/software/sorteros/build/chroot_apt.sh" "${USERPATCHES}/overlay/tmp/sorteros-chroot_apt.sh"
chmod +x "${USERPATCHES}/overlay/tmp/sorteros-chroot_apt.sh"
printf '%s\n' "${SORTEROS_BRANCH}" > "${USERPATCHES}/overlay/etc/sorteros/branch"

if compgen -G "${HOME}/.ssh/*.pub" >/dev/null; then
	echo "[sorteros-armbian] adding local SSH public keys for first boot access"
	cat "${HOME}"/.ssh/*.pub > "${USERPATCHES}/overlay/etc/sorteros/bootstrap_authorized_keys"
	chmod 0644 "${USERPATCHES}/overlay/etc/sorteros/bootstrap_authorized_keys"
else
	echo "[sorteros-armbian] WARNING: no ${HOME}/.ssh/*.pub keys found; SSH will need manual provisioning." >&2
fi

python3 "${SCRIPT_DIR}/render-camera-contract.py" \
	--config "${REPO_ROOT}/software/sorteros/build/config-cm5-vendor61.toml" \
	--branch "${SORTEROS_BRANCH}" \
	--out "${USERPATCHES}/overlay/etc/sorteros/camera-transport-target.json"

FALLBACK_RELATIVE_PATHS=(
	"software/sorter/backend/pyproject.toml"
	"software/sorter/backend/uv.lock"
	"software/sorter/backend/main.py"
	"software/sorter/backend/server/routers/cameras.py"
	"software/sorter/backend/server/shared_state.py"
	"software/sorter/backend/vision/camera.py"
	"software/sorter/backend/vision/camera_device.py"
	"software/sorter/backend/vision/media_plane.py"
	"software/sorter/backend/vision/ffmpeg_h264_source.py"
	"software/sorter/backend/vision/gstreamer_target_capture.py"
	"software/sorter/backend/vision/gstreamer_target_runtime.py"
	"software/sorter/backend/vision/h264_webrtc_bridge.py"
	"software/sorter/backend/vision/webrtc_transport.py"
	"software/sorter/backend/scripts/probe_camera_transport_stack.py"
	"software/sorter/backend/scripts/probe_camera_handle_stability.py"
	"software/sorter/backend/scripts/probe_gstreamer_target_capture_pipeline.py"
	"software/sorter/backend/scripts/probe_camera_calibration_ring.py"
	"software/sorter/backend/scripts/probe_webrtc_view_scaling.py"
	"software/sorter/backend/scripts/probe_rk3588_npu_stack.py"
)
NPU_MODEL_RELATIVE="software/training/rknn_bundles/c_channel_full_yolo26s_320_rk3588/results/c_channel_full_yolo26s_320_rk3588.rknn"
NPU_MODEL_SOURCE="${REPO_ROOT}/${NPU_MODEL_RELATIVE}"
missing_fallback=0
for fallback_relative in "${FALLBACK_RELATIVE_PATHS[@]}"; do
	if [[ ! -f "${REPO_ROOT}/${fallback_relative}" ]]; then
		echo "[sorteros-armbian] missing code fallback: ${REPO_ROOT}/${fallback_relative}" >&2
		missing_fallback=1
	fi
done

if [[ ${missing_fallback} -eq 0 && -f "${NPU_MODEL_SOURCE}" ]]; then
	echo "[sorteros-armbian] embedding camera transport code + NPU smoke fallback artifacts"
	mkdir -p "${USERPATCHES}/overlay/opt/sorteros/npu-smoke/$(dirname "${NPU_MODEL_RELATIVE}")"
	for fallback_relative in "${FALLBACK_RELATIVE_PATHS[@]}"; do
		mkdir -p "${USERPATCHES}/overlay/opt/sorteros/npu-smoke/$(dirname "${fallback_relative}")"
		cp "${REPO_ROOT}/${fallback_relative}" \
			"${USERPATCHES}/overlay/opt/sorteros/npu-smoke/${fallback_relative}"
	done
	cp "${NPU_MODEL_SOURCE}" \
		"${USERPATCHES}/overlay/opt/sorteros/npu-smoke/${NPU_MODEL_RELATIVE}"
else
	echo "[sorteros-armbian] ERROR: camera transport/NPU smoke artifacts are required for the RK3588 Phase 0 image." >&2
	echo "  missing model? ${NPU_MODEL_SOURCE}" >&2
	exit 1
fi

DTB_SOURCE="${SCRIPT_DIR}/artifacts/rk3588s-orangepi-cm5-tablet.dtb"
if [[ -f "${DTB_SOURCE}" ]]; then
	echo "[sorteros-armbian] adding CM5 tablet DTB from ${DTB_SOURCE}"
	mkdir -p "${USERPATCHES}/overlay/boot/dtb/rockchip"
	cp "${DTB_SOURCE}" "${USERPATCHES}/overlay/boot/dtb/rockchip/rk3588s-orangepi-cm5-tablet.dtb"
else
	echo "[sorteros-armbian] WARNING: ${DTB_SOURCE} missing; run fetch-live-cm5-dtb.sh before boot testing." >&2
fi

if [[ ${PREPARE_ONLY} -eq 1 ]]; then
	echo "[sorteros-armbian] userpatches prepared; stopping before compile.sh"
	exit 0
fi

echo "[sorteros-armbian] invoking Armbian build"
cd "${ARMBIAN_DIR}"
exec ./compile.sh \
	BOARD="${BOARD}" \
	BRANCH="${BRANCH}" \
	RELEASE="${RELEASE}" \
	BUILD_MINIMAL=yes \
	BUILD_DESKTOP=no \
	KERNEL_CONFIGURE=no \
	KERNEL_BTF=no \
	EXPERT=yes \
	SHARE_LOGS=no \
	INSTALL_HEADERS=yes \
	"${EXTRA_ARGS[@]}"
