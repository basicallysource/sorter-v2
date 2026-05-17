#!/usr/bin/env bash
# Start / stop the kickoff web UI as a background process on the Mac.
# Stores pid in .pid and logs to .serve.log next to this script.
# Manual control only — does NOT auto-start at login.
set -euo pipefail

cd "$(dirname "$0")"
PID_FILE=.pid
LOG_FILE=.serve.log
PORT=8780

is_alive() {
    [[ -f $PID_FILE ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-status}" in
    start)
        if is_alive; then
            echo "already running (pid $(cat "$PID_FILE")) on http://127.0.0.1:$PORT/"
            exit 0
        fi
        # uv sync is idempotent; safe to run every start
        uv sync --quiet
        nohup uv run uvicorn server:app --host 127.0.0.1 --port "$PORT" \
            --log-level info > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 1
        if is_alive; then
            echo "started (pid $(cat "$PID_FILE")) on http://127.0.0.1:$PORT/"
        else
            echo "FAILED to start; see $LOG_FILE"
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;
    stop)
        if is_alive; then
            pid=$(cat "$PID_FILE")
            kill "$pid"
            for _ in 1 2 3 4 5; do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.5
            done
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
            rm -f "$PID_FILE"
            echo "stopped"
        else
            echo "not running"
            rm -f "$PID_FILE"
        fi
        ;;
    restart)
        "$0" stop || true
        exec "$0" start
        ;;
    status)
        if is_alive; then
            echo "running (pid $(cat "$PID_FILE")) — http://127.0.0.1:$PORT/"
        else
            echo "not running"
        fi
        ;;
    logs)
        tail -n 200 -f "$LOG_FILE"
        ;;
    *)
        echo "usage: $0 {start|stop|restart|status|logs}" >&2
        exit 2
        ;;
esac
