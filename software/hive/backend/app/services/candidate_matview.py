"""Background refresh of the piece_has_candidates materialized view.

The view (see the a8c1d2e3f4a5 migration) precomputes which pieces have
same-piece candidate crops so the labeling grid can hash-join it instead of
running a correlated EXISTS per piece. Pieces only become visible in the grid
15 minutes after arrival (_old_enough), so as long as the refresh cadence is
comfortably inside that window the view is indistinguishable from live data.
"""

from __future__ import annotations

import threading

from sqlalchemy import text

from app.database import engine
from app.services.periodic import PeriodicWorker

REFRESH_INTERVAL_S = 300.0


def refresh_once() -> None:
    # CONCURRENTLY can't run inside a transaction, and the refresh is allowed
    # to outlive the app-wide statement timeout.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SET statement_timeout = 0"))
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY piece_has_candidates"))


_worker: PeriodicWorker | None = None
_worker_lock = threading.Lock()


def get_candidate_matview_worker() -> PeriodicWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = PeriodicWorker(
                "candidate-matview-worker", refresh_once, lambda: REFRESH_INTERVAL_S
            )
        return _worker
