"""The worker process: every background worker, and nothing else.

    HIVE_ROLE=worker python -m app.worker

Production runs it beside the web process, from the same image (service
``worker`` in docker-compose.prod.yml; agent-docs/process-roles.md). It starts
what an all-in-one process starts (``app.background``), then until SIGTERM:

- every ``WORKER_POLL_INTERVAL_S``, does what the web process asked of it (run
  a pass now, start or stop a catalog sync: ``worker_state`` requests);
- every ``WORKER_HEARTBEAT_INTERVAL_S``, reports itself and each of its workers
  to the database, which is what the admin pages show, and then touches
  ``WORKER_HEARTBEAT_FILE``: the container's healthcheck. A process that cannot
  reach the database stops touching it and turns unhealthy.

It serves no HTTP: nothing routes to it, and a file's age is all a healthcheck
needs. It runs no migrations either; the web process's start does.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path

from app.config import settings
from app.logging_config import configure_app_logging

logger = logging.getLogger("app.worker")


def run(stop: threading.Event) -> None:
    """Start the workers, then report and take requests until ``stop`` is set."""
    from app import background
    from app.database import SessionLocal
    from app.services import worker_state

    heartbeat_file = Path(settings.WORKER_HEARTBEAT_FILE)
    # Left by a previous run in this container: not this process's heartbeat.
    heartbeat_file.unlink(missing_ok=True)
    background.start()
    next_beat = 0.0
    failures = 0
    try:
        while not stop.is_set():
            db = SessionLocal()
            try:
                for done in background.serve_requests(db):
                    logger.info("worker: did %s, as the web process asked", done)
                if time.monotonic() >= next_beat:
                    worker_state.write_heartbeat(db, background.heartbeat_payload())
                    heartbeat_file.touch()
                    next_beat = time.monotonic() + settings.WORKER_HEARTBEAT_INTERVAL_S
                failures = 0
            except Exception:
                db.rollback()
                failures += 1
                if failures == 1 or failures % 30 == 0:
                    logger.exception("worker: could not report or take requests (%d in a row)", failures)
            finally:
                db.close()
            stop.wait(settings.WORKER_POLL_INTERVAL_S)
    finally:
        background.stop()
        logger.info("worker: stopped")


def main() -> int:
    configure_app_logging()
    if settings.HIVE_ROLE != "worker":
        logger.error(
            "app.worker runs the background workers, and HIVE_ROLE is %r. Set HIVE_ROLE=worker "
            "here and run the web process with HIVE_ROLE=web: a process with HIVE_ROLE=all "
            "already runs every worker, and two would run each one twice.",
            settings.HIVE_ROLE,
        )
        return 2
    stop = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        logger.info("worker: signal %d, stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    run(stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
