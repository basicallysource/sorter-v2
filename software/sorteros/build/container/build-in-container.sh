#!/usr/bin/env bash
# Runs the SorterOS image build in a container, for hosts that are not Linux
# (macOS with podman or docker). The container needs --privileged for loop
# devices and relies on the container VM's kernel having qemu-aarch64
# registered in binfmt_misc with the F flag (the podman machine does).
#
#   ./build-in-container.sh image                    build the builder image
#   ./build-in-container.sh extract <archive>        unpack a vendor .7z/.xz in build/cache/
#   ./build-in-container.sh build [build.py args]    e.g. build --config config-cm5.toml
#   ./build-in-container.sh shell                    shell in the working copy
#
# Results land in build/out/. The working copy and the loop-mounted image live
# in the volume $VOLUME, not on the host's file system: loop mounts and
# pnpm install over a macOS mount are slow. `podman volume rm` frees the space.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SORTEROS=$(cd "$HERE/../.." && pwd)
BUILD=$SORTEROS/build
ENGINE=${CONTAINER_ENGINE:-$(command -v podman || command -v docker)}
IMAGE=${BUILDER_IMAGE:-sorteros-builder}
VOLUME=${BUILDER_VOLUME:-sorteros-build-work}

mkdir -p "$BUILD/cache" "$BUILD/out"

cmd=${1:-}
[ -n "$cmd" ] || { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
shift

if [ "$cmd" = image ]; then
    exec "$ENGINE" build -t "$IMAGE" -f "$HERE/Containerfile" "$HERE"
fi

flags=(--rm --privileged
    -v /dev:/dev
    -v "$SORTEROS:/src:ro"
    -v "$BUILD/cache:/cache"
    -v "$BUILD/out:/out"
    -v "$VOLUME:/work")
[ "$cmd" = shell ] && flags+=(-it)

exec "$ENGINE" run "${flags[@]}" "$IMAGE" "$cmd" "$@"
