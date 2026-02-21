"""Lightweight server for hardware testing/debugging.

Initializes only Jose's hardware module (COBS binary protocol) and
starts the FastAPI server on port 8000. No vision, ML, or IRL dependencies.

Usage:
    uv run python hardware_server.py
"""

import logging
from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
from server.api import app, setHardwareInterfaces, _initHardware
import uvicorn


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("hardware_server")

    log.info("Discovering hardware...")
    interfaces = _initHardware()

    if not interfaces:
        log.warning("No hardware found. Endpoints will return empty results. Use /hardware/devices/rescan to retry.")
    else:
        log.info(f"Ready with {len(interfaces)} device(s): {list(interfaces.keys())}")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
