#!/usr/bin/env bash
set -euo pipefail

# Build ffmpeg-rockchip in an isolated prefix without replacing system ffmpeg.
# The backend media-plane probe auto-detects this default install path.

REPO_URL="${FFMPEG_ROCKCHIP_REPO:-https://github.com/nyanmisaka/ffmpeg-rockchip.git}"
REF="${FFMPEG_ROCKCHIP_REF:-master}"
BUILD_DIR="${FFMPEG_ROCKCHIP_BUILD_DIR:-$HOME/build/ffmpeg-rockchip}"
PREFIX="${FFMPEG_ROCKCHIP_PREFIX:-$HOME/.local/ffmpeg-rockchip}"
JOBS="${FFMPEG_ROCKCHIP_JOBS:-4}"

if ! command -v git >/dev/null; then
  echo "git is required" >&2
  exit 1
fi
if ! command -v pkg-config >/dev/null; then
  echo "pkg-config is required" >&2
  exit 1
fi
for pkg in rockchip_mpp librga libdrm; do
  if ! pkg-config --exists "$pkg"; then
    echo "missing pkg-config package: $pkg" >&2
    echo "On Debian/Ubuntu install: librockchip-mpp-dev librga-dev libdrm-dev" >&2
    exit 1
  fi
done

mkdir -p "$(dirname "$BUILD_DIR")"
if [[ ! -d "$BUILD_DIR/.git" ]]; then
  git clone --depth=1 --branch "$REF" "$REPO_URL" "$BUILD_DIR"
else
  git -C "$BUILD_DIR" fetch --depth=1 origin "$REF"
  git -C "$BUILD_DIR" reset --hard FETCH_HEAD
fi

cd "$BUILD_DIR"
./configure \
  --prefix="$PREFIX" \
  --enable-gpl \
  --enable-version3 \
  --enable-libdrm \
  --enable-rkmpp \
  --enable-rkrga \
  --disable-doc \
  --disable-debug \
  --disable-ffplay

make -j"$JOBS"
make install

"$PREFIX/bin/ffmpeg" -hide_banner -encoders | grep -E "h264_rkmpp|hevc_rkmpp|mjpeg_rkmpp"
"$PREFIX/bin/ffmpeg" -hide_banner -filters | grep -E "scale_rkrga|vpp_rkrga|overlay_rkrga"

echo "Installed ffmpeg-rockchip to $PREFIX"
