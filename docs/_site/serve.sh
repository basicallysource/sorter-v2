#!/bin/bash
# Start/stop/restart/status the local Jekyll docs server.
# Uses homebrew Ruby; auto-reloads the browser on file changes via --livereload.
#
# Usage: ./serve.sh [start|stop|restart|status|logs]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.jekyll.pid"
LOG_FILE="$SCRIPT_DIR/.jekyll.log"
RUBY=/opt/homebrew/opt/ruby/bin/ruby
BUNDLE=/opt/homebrew/opt/ruby/bin/bundle
PORT=4000

is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

cmd_start() {
    if is_running; then
        echo "already running (pid $(cat "$PID_FILE")) — http://localhost:$PORT"
        return
    fi
    echo "starting Jekyll on http://localhost:$PORT ..."
    cd "$SCRIPT_DIR"
    PATH="/opt/homebrew/opt/ruby/bin:$PATH" \
        "$BUNDLE" exec jekyll serve \
            --port "$PORT" \
            --livereload \
            --watch \
            --trace \
            > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "started (pid $!) — logs: $LOG_FILE"
}

cmd_stop() {
    if ! is_running; then
        echo "not running"
        [[ -f "$PID_FILE" ]] && rm "$PID_FILE"
        return
    fi
    echo "stopping (pid $(cat "$PID_FILE")) ..."
    kill "$(cat "$PID_FILE")"
    rm "$PID_FILE"
    echo "stopped"
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

cmd_status() {
    if is_running; then
        echo "running (pid $(cat "$PID_FILE")) — http://localhost:$PORT"
    else
        echo "not running"
    fi
}

cmd_logs() {
    if [[ ! -f "$LOG_FILE" ]]; then
        echo "no log file yet"
        return
    fi
    tail -f "$LOG_FILE"
}

case "${1:-start}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    logs)    cmd_logs ;;
    *)
        echo "usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
