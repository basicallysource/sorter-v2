#!/usr/bin/env bash
# Launch the SorterOS Kickoff web UI on http://127.0.0.1:8765
# Manual start only — does NOT auto-boot. Ctrl+C to stop.
set -euo pipefail
cd "$(dirname "$0")"
uv sync
exec uv run uvicorn server:app --host 127.0.0.1 --port 8780 --log-level info
