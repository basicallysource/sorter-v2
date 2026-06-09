#!/usr/bin/env bash
# Build a working fp16 RK3588 RKNN from a YOLO best.pt, in a pinned x86 container.
#
#   ./build.sh <best.pt> <out.rknn> [imgsz]
#
# rknn-toolkit2 is x86-only; on Apple Silicon this runs under QEMU emulation.
# The image is built once and cached, so repeated conversions are fast.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <best.pt> <out.rknn> [imgsz=320]" >&2
  exit 2
fi

PT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT_DIR="$(cd "$(dirname "$2")" && pwd)"
OUT_NAME="$(basename "$2")"
IMGSZ="${3:-320}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker build --platform linux/amd64 -t lego-rknn-builder "$HERE"
docker run --rm --platform linux/amd64 \
  -v "$(dirname "$PT"):/in:ro" \
  -v "$OUT_DIR:/out" \
  lego-rknn-builder \
  --pt "/in/$(basename "$PT")" --out "/out/$OUT_NAME" --imgsz "$IMGSZ"
