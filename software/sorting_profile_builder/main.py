import logging
import os
import sys
from datetime import datetime

import uvicorn
from global_config import mkGlobalConfig
from db import initDb, PartsData, reloadPartsData
from parts_cache import SyncManager
from server import mkApp


def setupLogging():
    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"{timestamp}.log")

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("sorting_profile_builder").setLevel(logging.DEBUG)
    return log_file


def main():
    log_file = setupLogging()
    logger = logging.getLogger("sorting_profile_builder")
    logger.info(f"Logging to {log_file}")

    gc = mkGlobalConfig()
    conn = initDb(gc.db_path)
    parts_data = PartsData()
    reloadPartsData(conn, parts_data)
    sync = SyncManager()
    app = mkApp(gc, conn, parts_data, sync)
    logger.info(f"Starting server on port {gc.port}")
    uvicorn.run(app, host="0.0.0.0", port=gc.port)


if __name__ == "__main__":
    main()
