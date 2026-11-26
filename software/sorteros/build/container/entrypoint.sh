#!/usr/bin/env bash
# Runs inside the builder container (see build-in-container.sh).
#
#   entrypoint.sh build [build.py args]   sync the source, run build.py, copy results to /out
#   entrypoint.sh extract <archive>       unpack a vendor .7z/.xz into the cache
#   entrypoint.sh shell                   bash in the synced tree
#
# /src is the checkout (read-only), /work a volume holding the working copy
# and the build output, /out the host's build/out.
set -euo pipefail

SRC=/src
WORK=/work/sorteros
BUILD=$WORK/build
CACHE=$BUILD/cache   # a symlink to /cache, see sync_src
MNT=/mnt/sorteros-build

log() { echo "[container $(date +%H:%M:%S)] $*"; }

sync_src() {
    mkdir -p "$WORK"
    # Build products and installed packages stay out of both directions.
    rsync -a --delete \
        --exclude='/build/out/' --exclude='/build/cache/' \
        --exclude='node_modules/' --exclude='.svelte-kit/' \
        --exclude='/portal/frontend/build/' --exclude='/sorteros-setup/' \
        --exclude='__pycache__/' \
        "$SRC/" "$WORK/"
    mkdir -p "$BUILD/out"
    # The base image stays on the host (/cache is build/cache there).
    rm -rf "$CACHE"
    ln -s /cache "$CACHE"
}

# build.py leaves its mounts and loop device behind when it dies; a loop
# device outlives the container because it belongs to the VM's kernel.
release_mounts() {
    for d in dev/pts dev proc sys; do umount "$MNT/$d" 2>/dev/null || umount -l "$MNT/$d" 2>/dev/null || true; done
    umount "$MNT" 2>/dev/null || true
    if [ -f "$BUILD/out/work.img" ]; then
        losetup -j "$BUILD/out/work.img" -O NAME -n 2>/dev/null | xargs -r -n1 losetup -d || true
    fi
}

cmd=${1:-shell}
shift || true

case "$cmd" in
    extract)
        archive=${1:?usage: extract <archive in cache/>}
        cd /cache
        case "$archive" in
            *.7z) 7z x -y "$archive" ;;
            *.xz) xz -dk "$archive" ;;
            *) echo "unknown archive type: $archive" >&2; exit 2 ;;
        esac
        ;;
    build)
        sync_src
        trap release_mounts EXIT
        stamp=$(mktemp)
        cd "$BUILD"
        python3 build.py "$@"
        log "copying results to build/out"
        find out -maxdepth 1 -type f \( -name 'sorteros-v*.img' -o -name 'sorteros-v*.zip' \) -newer "$stamp" \
            -exec cp --sparse=always -v {} /out/ \;
        ;;
    shell)
        sync_src
        cd "$BUILD"
        exec bash
        ;;
    *)
        echo "unknown command: $cmd" >&2
        exit 2
        ;;
esac
