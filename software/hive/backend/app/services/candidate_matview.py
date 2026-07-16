"""Background refresh of the piece_has_candidates materialized view.

The view (see the a8c1d2e3f4a5 migration) precomputes which pieces have
same-piece candidate crops so the labeling grid can hash-join it instead of
running a correlated EXISTS per piece. Pieces only become visible in the grid
15 minutes after arrival (_old_enough), so as long as the refresh cadence is
comfortably inside that window the view is indistinguishable from live data.
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_S = 300.0


class CandidateMatviewWorker:
    """Daemon thread that refreshes piece_has_candidates on a fixed cadence."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_lock = threading.Lock()

    def start(self) -> None:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="candidate-matview-worker"
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        logger.info("CandidateMatviewWorker: started")
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=REFRESH_INTERVAL_S)
            if self._stop_event.is_set():
                break
            self._refresh_once()
        logger.info("CandidateMatviewWorker: stopped")

    def _refresh_once(self) -> None:
        started = time.monotonic()
        try:
            # CONCURRENTLY can't run inside a transaction, and the refresh is
            # allowed to outlive the app-wide statement timeout.
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text("SET statement_timeout = 0"))
                conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY piece_has_candidates"))
            logger.info(
                "CandidateMatviewWorker: refreshed in %.1fs", time.monotonic() - started
            )
        except Exception:
            logger.exception("CandidateMatviewWorker: refresh failed")


_worker: CandidateMatviewWorker | None = None
_worker_lock = threading.Lock()


def get_candidate_matview_worker() -> CandidateMatviewWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = CandidateMatviewWorker()
        return _worker
