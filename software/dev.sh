#!/usr/bin/env bash
# Unified dev runner / watchdog for the LEGO sorter.
# Starts the full machine client backend + frontend (vite) with:
#   - Color-coded, prefixed log output
#   - Auto-restart on crash (with backoff)
#   - Graceful shutdown on Ctrl+C
#
# Usage:
#   ./dev.sh            # start both
#   ./dev.sh backend    # full machine backend only
#   ./dev.sh api        # API-only backend (no controller / hardware)
#   ./dev.sh frontend   # frontend only
#   ./dev.sh --dump     # also write all output to logs/<datetime>.log

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$ROOT/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
DIM='\033[2m'
RESET='\033[0m'

# PIDs we manage
BACKEND_PID=""
FRONTEND_PID=""
SHUTTING_DOWN=false

log() { echo -e "${DIM}[dev]${RESET} $*"; }
log_err() { echo -e "${RED}[dev]${RESET} $*" >&2; }

cleanup() {
    SHUTTING_DOWN=true
    echo ""
    log "Shutting down..."
    [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null && log "Stopped backend  (PID $BACKEND_PID)"
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && log "Stopped frontend (PID $FRONTEND_PID)"
    # Kill any child processes in our process group
    kill 0 2>/dev/null || true
    wait 2>/dev/null || true
    log "Done."
    exit 0
}

trap cleanup SIGINT SIGTERM

kill_port() {
    local port=$1
    local pids
    pids=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        log "${YELLOW}Killing stale process(es) on port $port${RESET}"
        echo "$pids" | xargs kill -9 2>/dev/null || true
        sleep 0.5
    fi
}

load_env() {
    if [ -f "$ENV_FILE" ]; then
        set -a
        # Source but strip 'export' keywords so it works with plain assignment too
        eval "$(sed 's/^export //' "$ENV_FILE")"
        set +a
    fi
}

run_backend() {
    local attempt=0
    local max_backoff=10

    while ! $SHUTTING_DOWN; do
        attempt=$((attempt + 1))
        if [ "$attempt" -gt 1 ]; then
            local delay=$((attempt > max_backoff ? max_backoff : attempt))
            log "${YELLOW}Backend crashed. Restarting in ${delay}s (attempt $attempt)...${RESET}"
            sleep "$delay"
        fi

        log "${GREEN}Starting backend...${RESET}"
        (
            cd "$ROOT/sorter/backend"
            exec uv run python supervisor.py 2>&1 \
                | sed -u "s/^/${GREEN}[backend]${RESET}  /"
        ) &
        BACKEND_PID=$!
        wait "$BACKEND_PID" 2>/dev/null || true
        BACKEND_PID=""

        $SHUTTING_DOWN && break

        # Reset attempt counter after 30s of successful running
        # (checked implicitly: if we get here quickly, it was a crash)
    done
}

run_api_only_backend() {
    local attempt=0
    local max_backoff=10

    while ! $SHUTTING_DOWN; do
        attempt=$((attempt + 1))
        if [ "$attempt" -gt 1 ]; then
            local delay=$((attempt > max_backoff ? max_backoff : attempt))
            log "${YELLOW}API backend crashed. Restarting in ${delay}s (attempt $attempt)...${RESET}"
            sleep "$delay"
        fi

        log "${GREEN}Starting API-only backend...${RESET}"
        (
            cd "$ROOT/sorter/backend"
            exec uv run uvicorn server.api:app --host "${SORTER_API_HOST:-127.0.0.1}" --port 8000 2>&1 \
                | sed -u "s/^/${GREEN}[api]${RESET}      /"
        ) &
        BACKEND_PID=$!
        wait "$BACKEND_PID" 2>/dev/null || true
        BACKEND_PID=""

        $SHUTTING_DOWN && break
    done
}

run_frontend() {
    local attempt=0
    local max_backoff=10

    while ! $SHUTTING_DOWN; do
        attempt=$((attempt + 1))
        if [ "$attempt" -gt 1 ]; then
            local delay=$((attempt > max_backoff ? max_backoff : attempt))
            log "${YELLOW}Frontend crashed. Restarting in ${delay}s (attempt $attempt)...${RESET}"
            sleep "$delay"
        fi

        log "${BLUE}Starting frontend...${RESET}"
        (
            cd "$ROOT/sorter/frontend"
            exec pnpm dev 2>&1 \
                | sed -u "s/^/${BLUE}[frontend]${RESET} /"
        ) &
        FRONTEND_PID=$!
        wait "$FRONTEND_PID" 2>/dev/null || true
        FRONTEND_PID=""

        $SHUTTING_DOWN && break
    done
}

# --- Main ---

DUMP=false
PARSED_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --dump) DUMP=true ;;
        *) PARSED_ARGS+=("$arg") ;;
    esac
done
set -- ${PARSED_ARGS[@]+"${PARSED_ARGS[@]}"}

MODE="${1:-all}"

if $DUMP; then
    LOG_DIR="$ROOT/logs"
    mkdir -p "$LOG_DIR"
    LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d_%H-%M-%S).log"
    # Tee everything: keep colors on terminal, strip ANSI codes in the file
    exec > >(tee >(sed -u $'s/\033\\[[0-9;]*[a-zA-Z]//g' >> "$LOG_FILE")) 2>&1
    log "${CYAN}Dumping logs to $LOG_FILE${RESET}"
fi

log "${CYAN}LEGO Sorter Dev Runner${RESET}"
log "Mode: $MODE"

load_env

# ADB port forward for Android camera (IP Webcam) — silently skip if no device
if command -v adb &>/dev/null && adb devices 2>/dev/null | grep -q "device$"; then
    adb forward tcp:8080 tcp:8080 2>/dev/null && log "ADB forward: tcp:8080 -> phone:8080"
fi

case "$MODE" in
    backend)
        kill_port 8000
        kill_port 8001
        run_backend
        ;;
    api)
        kill_port 8000
        run_api_only_backend
        ;;
    frontend)
        kill_port 5173
        run_frontend
        ;;
    all|*)
        kill_port 8000
        kill_port 8001
        kill_port 5173
        run_backend &
        run_frontend &
        wait
        ;;
esac
