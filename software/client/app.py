"""Station server entrypoint — the single thing the AGX runs (replaces main.py + api_only.py).

Boots into IDLE: it serves the web UI + API on 0.0.0.0:8000 and owns no hardware until the
user starts a run (or, later, a calibration) from the browser. This is what the systemd unit
launches at boot, so the sorter is reachable at http://<host>.local:8000 with nothing typed
on the AGX.
"""

from dotenv import load_dotenv
from pathlib import Path

# Load .env before importing anything that reads env at import time (config_paths, global_config).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncio
import signal
import socket

import uvicorn

PORT = 8000


def _banner(state: str) -> None:
    """Plain stdout print so the terminal always shows server status (uvicorn's banner is
    suppressed at log_level=error and the app logger is buffered)."""
    host = socket.gethostname()
    if state == "starting":
        print("\n  Starting Station server…", flush=True)
    elif state == "running":
        print(
            f"\n  Station server running — open from any device on the LAN:\n"
            f"    http://{host}.local:{PORT}\n"
            f"    http://localhost:{PORT}  (on the AGX)\n"
            f"  Press Ctrl-C to stop.\n",
            flush=True,
        )
    elif state == "stopped":
        print("  Station server stopped cleanly.\n", flush=True)

from global_config import make_global_config
from aruco_config_manager import ArucoConfigManager
from config_paths import config_path
from run_recorder import RunRecorder
from station import StationManager
import server.api as api
from server.static_ui import mount_ui


def main() -> None:
    _banner("starting")
    gc = make_global_config()
    gc.run_recorder = RunRecorder(gc)
    api.set_global_config(gc)

    aruco_manager = ArucoConfigManager(str(config_path("aruco_config.json")))
    api.set_aruco_manager(aruco_manager)

    station = StationManager(gc, aruco_manager)
    api.set_station(station)

    # Serve the built SPA last so its catch-all never shadows the API routes above.
    mount_ui(api.app)

    config = uvicorn.Config(
        api.app,
        host="0.0.0.0",
        port=8000,
        log_level="error",
        ws="wsproto",
        # Backstop: never wait more than a few seconds for connections (e.g. MJPEG streams)
        # to drain on shutdown.
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    # We install our own signal handlers (instead of uvicorn's) so Ctrl-C/SIGTERM first
    # stops streams + releases all hardware, then unwinds the server — clean exit in any mode.
    server.install_signal_handlers = lambda: None

    async def serve() -> None:
        loop = asyncio.get_running_loop()
        stopping = {"v": False}

        def handle_signal() -> None:
            if stopping["v"]:
                return
            stopping["v"] = True
            gc.logger.info("Shutdown signal received; stopping streams and releasing hardware...")
            api.shutdown_event.set()
            try:
                station.shutdown()
            finally:
                server.should_exit = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

        async def announce() -> None:
            while not server.started:
                await asyncio.sleep(0.05)
            _banner("running")

        asyncio.create_task(announce())
        await server.serve()

    gc.logger.info("Station server starting in IDLE on 0.0.0.0:8000")
    asyncio.run(serve())
    _banner("stopped")


if __name__ == "__main__":
    main()
