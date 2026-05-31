#!/usr/bin/env bash
# Build (and optionally push) the Vast.ai trainer image.
#
#   ./build.sh                # build linux/amd64 image, tag :latest + :YYYYMMDD
#   ./build.sh --push         # build and push both tags
#
# Requires docker buildx (Docker Desktop ships with it). On Apple Silicon
# this cross-builds for amd64, which is what Vast.ai hosts run.
set -euo pipefail

cd "$(dirname "$0")"

IMAGE=${IMAGE:-roothirsch/lego-sorter-training-image}
DATE_TAG=$(date -u +%Y%m%d)
PLATFORM=${PLATFORM:-linux/amd64}

PUSH=0
for arg in "$@"; do
    case $arg in
        --push) PUSH=1 ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

ACTION="--load"
if [ "$PUSH" -eq 1 ]; then
    ACTION="--push"
fi

docker buildx build \
    --platform "$PLATFORM" \
    -f Dockerfile.trainer \
    -t "$IMAGE:latest" \
    -t "$IMAGE:$DATE_TAG" \
    $ACTION \
    .

echo
echo "Tags built: $IMAGE:latest, $IMAGE:$DATE_TAG"
if [ "$PUSH" -eq 0 ]; then
    echo "Local-only build (run with --push to publish, or):"
    echo "  docker push $IMAGE:latest"
    echo "  docker push $IMAGE:$DATE_TAG"
fi
