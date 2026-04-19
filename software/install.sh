#!/usr/bin/env bash
# install.sh — one-shot installer for the LEGO Sorter on a fresh
# Debian / Ubuntu / Raspberry Pi OS box.
#
# Usage:
#   ./install.sh                 # install everything in dev mode
#   ./install.sh --as-service    # also build UI and install systemd units
#   ./install.sh --skip-apt      # skip apt-get steps (when packages already installed)
#   ./install.sh --help

set -euo pipefail

AS_SERVICE=false
SKIP_APT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --as-service) AS_SERVICE=true; shift;;
        --skip-apt)   SKIP_APT=true;   shift;;
        --help|-h)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0;;
        *)
            echo "unknown arg: $1" >&2
            exit 1;;
    esac
done

# colors
BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; RESET='\033[0m'
log()  { echo -e "${BLUE}[install]${RESET} $*"; }
ok()   { echo -e "${GREEN}[install]${RESET} $*"; }
warn() { echo -e "${YELLOW}[install]${RESET} $*"; }
err()  { echo -e "${RED}[install]${RESET} $*" >&2; }

SOFTWARE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SOFTWARE_DIR/.." && pwd)"

if [[ ! -f "$SOFTWARE_DIR/dev.sh" ]]; then
    err "install.sh must live next to dev.sh inside software/"
    exit 1
fi

log "Repo root:    $REPO_ROOT"
log "Software dir: $SOFTWARE_DIR"
log "Mode:         $([[ $AS_SERVICE == true ]] && echo 'systemd service' || echo 'dev')"

# ─────────────────────────────────────────────────────────────────────────────
# 1. System packages
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_APT" == "false" ]]; then
    log "Installing system packages via apt..."
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        git \
        curl ca-certificates \
        build-essential pkg-config \
        libgl1 libglib2.0-0 \
        lsof \
        v4l-utils \
        udev
    ok "apt packages installed"
else
    warn "Skipping apt step (--skip-apt)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. udev rule for Pico boards (plugdev group + uaccess tag)
# ─────────────────────────────────────────────────────────────────────────────
if [[ -d /etc/udev/rules.d ]]; then
    log "Installing udev rule for Raspberry Pi Pico boards..."
    sudo cp "$SOFTWARE_DIR/systemd/99-sorter-pico.rules" /etc/udev/rules.d/
    # Ensure plugdev group exists and current user is a member so headless /
    # non-seat access keeps working. uaccess still covers the active desktop
    # seat user without requiring logout/login.
    if ! getent group plugdev >/dev/null; then
        sudo groupadd --system plugdev || warn "failed to create plugdev group"
    fi
    if ! id -nG "$USER" | tr ' ' '\n' | grep -qx plugdev; then
        sudo usermod -aG plugdev "$USER" \
            && warn "Added $USER to plugdev — log out/in for headless/ssh sessions to pick it up" \
            || warn "failed to add $USER to plugdev"
    fi
    sudo udevadm control --reload-rules 2>/dev/null \
        || warn "udevadm reload failed (ok inside containers)"
    sudo udevadm trigger 2>/dev/null || true
    ok "udev rule installed"
else
    warn "/etc/udev/rules.d not present — skipping udev rule"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. uv (Python toolchain)
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    log "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv &>/dev/null; then
    err "uv is still not on PATH after install — open a new shell and re-run"
    exit 1
fi
ok "uv: $(uv --version)"

# ─────────────────────────────────────────────────────────────────────────────
# 4. Node.js + pnpm (UI toolchain)
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    log "Installing Node.js 20.x..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null
    sudo apt-get install -y -qq nodejs
fi
ok "node: $(node --version)"

if ! command -v pnpm &>/dev/null; then
    log "Installing pnpm..."
    sudo npm install -g pnpm >/dev/null
fi
ok "pnpm: $(pnpm --version)"

# ─────────────────────────────────────────────────────────────────────────────
# 5. .env files with discovered repo paths
# ─────────────────────────────────────────────────────────────────────────────
ENV_FILE="$SOFTWARE_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    warn ".env already exists at $ENV_FILE — leaving it alone"
else
    log "Writing .env with discovered repo paths..."
    cat > "$ENV_FILE" <<EOF
export DEBUG_LEVEL=2

export MACHINE_SPECIFIC_PARAMS_PATH="$SOFTWARE_DIR/machine.example.toml"
export SORTING_PROFILE_PATH="$SOFTWARE_DIR/sorter/backend/sorting_profile.json"

export BL_CONSUMER_KEY="no"
export BL_CONSUMER_SECRET="no"
export BL_TOKEN_VALUE="no"
export BL_TOKEN_SECRET="no"
EOF
    ok ".env written"
fi

UI_ENV="$SOFTWARE_DIR/sorter/frontend/.env"
if [[ ! -f "$UI_ENV" ]]; then
    cp "$SOFTWARE_DIR/sorter/frontend/.env.example" "$UI_ENV"
    ok "sorter/frontend/.env written"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. Python dependencies (slow on first run — uv fetches Python 3.13)
# ─────────────────────────────────────────────────────────────────────────────
log "Running uv sync (this is the slow one on a clean install)..."
( cd "$SOFTWARE_DIR/sorter/backend" && uv sync )
ok "Python deps installed"

# ─────────────────────────────────────────────────────────────────────────────
# 7. UI dependencies
# ─────────────────────────────────────────────────────────────────────────────
log "Running pnpm install..."
( cd "$SOFTWARE_DIR/sorter/frontend" && pnpm install --frozen-lockfile )
ok "UI deps installed"

# ─────────────────────────────────────────────────────────────────────────────
# 8. systemd service install (optional)
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$AS_SERVICE" == "true" ]]; then
    log "Building UI for production..."
    ( cd "$SOFTWARE_DIR/sorter/frontend" && pnpm build )

    log "Installing systemd units..."
    UV_BIN="$(command -v uv)"
    PNPM_BIN="$(command -v pnpm)"

    for unit in lego-sorter-backend.service lego-sorter-ui.service; do
        sed -e "s|__USER__|$USER|g" \
            -e "s|__SOFTWARE_DIR__|$SOFTWARE_DIR|g" \
            -e "s|__UV_BIN__|$UV_BIN|g" \
            -e "s|__PNPM_BIN__|$PNPM_BIN|g" \
            "$SOFTWARE_DIR/systemd/$unit" \
            | sudo tee "/etc/systemd/system/$unit" >/dev/null
    done

    sudo systemctl daemon-reload
    sudo systemctl enable --now lego-sorter-backend.service lego-sorter-ui.service
    ok "Services installed and started"
    log "Backend logs:  sudo journalctl -u lego-sorter-backend -f"
    log "UI logs:       sudo journalctl -u lego-sorter-ui -f"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────────
echo
ok "Install complete."
echo
if [[ "$AS_SERVICE" == "true" ]]; then
    echo "Sorter is running as a systemd service."
    echo "Open  http://localhost:5173/  in a browser on the sorter host."
else
    echo "Run the dev runner from $SOFTWARE_DIR:"
    echo "  ./dev.sh"
    echo "Then open  http://localhost:5173/  in a browser."
fi
