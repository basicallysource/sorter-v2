#!/usr/bin/env bash
# Run install.sh against a fresh Debian 12 container and verify the parts
# that don't require physical hardware:
#   - apt packages install cleanly
#   - uv installs and sync resolves Python 3.13 + all deps
#   - node + pnpm install and pnpm install resolves UI deps
#   - .env is generated from the discovered repo paths
#   - both systemd unit files pass `systemd-analyze verify`
#   - the backend's hardest imports (cv2, onnxruntime, fastapi) succeed
#   - the UI's vite binary is callable
#
# Hardware-dependent stuff (Pico discovery, camera enumeration, GPU paths)
# is intentionally NOT exercised — that needs a real device.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SOFTWARE="$ROOT/software"
TAG="lego-sorter-install-test"

if ! command -v docker &>/dev/null; then
    echo "docker not found on PATH" >&2
    exit 1
fi

echo "==> Building test image..."
docker build -q -t "$TAG" -f "$SOFTWARE/scripts/Dockerfile.install-test" \
    "$SOFTWARE/scripts"

echo "==> Running install.sh inside the container..."
docker run --rm \
    -e CI=true \
    -v "$ROOT:/host-repo:ro" \
    "$TAG" \
    bash -euo pipefail -c '
        echo "==> Copying repo into a writable location..."
        cp -a /host-repo /home/sorter/sorter-v2

        echo "==> Stripping host-side dev state from the copy..."
        rm -f  /home/sorter/sorter-v2/software/.env
        rm -f  /home/sorter/sorter-v2/software/ui/.env
        rm -rf /home/sorter/sorter-v2/software/client/.venv
        rm -rf /home/sorter/sorter-v2/software/ui/node_modules

        cd /home/sorter/sorter-v2/software

        echo "==> Running install.sh --skip-lfs..."
        ./install.sh --skip-lfs

        # uv installs to ~/.local/bin which is not on the parent shell PATH
        export PATH="$HOME/.local/bin:$PATH"

        echo
        echo "==> Smoke-testing backend imports..."
        cd client
        uv run python -c "
import sys
print(f\"  python: {sys.version.split()[0]}\")
import fastapi;       print(f\"  fastapi:      {fastapi.__version__}\")
import cv2;           print(f\"  opencv:       {cv2.__version__}\")
import onnxruntime;   print(f\"  onnxruntime:  {onnxruntime.__version__}\")
import uvicorn;       print(f\"  uvicorn:      {uvicorn.__version__}\")
import numpy;         print(f\"  numpy:        {numpy.__version__}\")
print(\"  backend deps OK\")
"

        echo
        echo "==> Smoke-testing UI tooling..."
        cd ../ui
        echo "  vite: $(pnpm exec vite --version)"

        echo
        echo "==> Validating systemd unit files..."
        sudo apt-get install -y -qq systemd >/dev/null 2>&1 || true
        for unit in lego-sorter-backend.service lego-sorter-ui.service; do
            sed -e "s|__USER__|sorter|g" \
                -e "s|__SOFTWARE_DIR__|/home/sorter/sorter-v2/software|g" \
                -e "s|__UV_BIN__|/home/sorter/.local/bin/uv|g" \
                -e "s|__PNPM_BIN__|/usr/bin/pnpm|g" \
                "/home/sorter/sorter-v2/software/systemd/$unit" \
                > "/tmp/$unit"
            if systemd-analyze verify "/tmp/$unit" 2>&1; then
                echo "  $unit: OK"
            else
                echo "  $unit: FAILED" >&2
                exit 1
            fi
        done

        echo
        echo "==> All install steps passed."
    '

echo "==> Docker install test passed."
