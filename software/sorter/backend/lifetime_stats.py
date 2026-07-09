from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from global_config import GlobalConfig
from local_state import local_state_db_path

# Durable, machine-lifetime cumulative stats — survives the dev soft-restart
# (os._exit) the same way piece_records does, because it never relies on a
# graceful shutdown. The only signal nothing else captures durably is TIME:
# how long the machine has been powered and how long it has actively sorted.
# Both are accumulated into per-hour buckets by a heartbeat flush, so a crash
# loses at most one flush interval (~10s) rather than the whole run. Piece
# counts and per-day piece activity are derived live from piece_records (same
# DB), so they are never double-counted here. Lifetime totals are just a SUM
# over the buckets; per-day/per-hour breakdowns fall straight out of the keys.

SECONDS_PER_HOUR = 3600

_INIT_LOCK = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    db_path = local_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    _ensureInitialized()
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def _ensureInitialized() -> None:
    global _initialized
    if _initialized:
        return
    with _INIT_LOCK:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS lifetime_hourly ("
                "hour_start INTEGER PRIMARY KEY, "
                "seconds_powered REAL NOT NULL DEFAULT 0, "
                "seconds_sorted REAL NOT NULL DEFAULT 0, "
                "updated_at REAL"
                ")"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def _hourBucket(ts: float) -> int:
    return int(ts // SECONDS_PER_HOUR) * SECONDS_PER_HOUR


def accumulate(*, hour_start: int, powered_delta_s: float, sorted_delta_s: float, now: float) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT INTO lifetime_hourly (hour_start, seconds_powered, seconds_sorted, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(hour_start) DO UPDATE SET "
            "seconds_powered = seconds_powered + excluded.seconds_powered, "
            "seconds_sorted = seconds_sorted + excluded.seconds_sorted, "
            "updated_at = excluded.updated_at",
            (hour_start, powered_delta_s, sorted_delta_s, now),
        )
        conn.commit()


class LifetimeStatsTracker:
    def __init__(self, gc: GlobalConfig):
        self.gc = gc
        self._running = False
        self._lock = threading.Lock()
        self._last_flush_mono = time.monotonic()

    # Flush the elapsed wall-time delta into the current hour bucket, attributing
    # it to "sorted" only while the machine is actively running. Shared monotonic
    # cursor means transition hooks and the periodic heartbeat can never double
    # count the same interval.
    def flush(self) -> None:
        with self._lock:
            self._flushLocked()

    def markRunning(self) -> None:
        with self._lock:
            self._flushLocked()
            self._running = True

    def markStopped(self) -> None:
        with self._lock:
            self._flushLocked()
            self._running = False

    def _flushLocked(self) -> None:
        mono = time.monotonic()
        delta = mono - self._last_flush_mono
        self._last_flush_mono = mono
        if delta <= 0:
            return
        wall = time.time()
        sorted_delta = delta if self._running else 0.0
        try:
            accumulate(
                hour_start=_hourBucket(wall),
                powered_delta_s=delta,
                sorted_delta_s=sorted_delta,
                now=wall,
            )
        except Exception as e:
            self.gc.logger.warning(f"LifetimeStatsTracker: flush failed: {e}")


def _piecesByDay(conn: sqlite3.Connection, since: float) -> dict[str, dict[str, int]]:
    # seen_at is a unix timestamp; bucket to local-day via SQLite's date().
    # Scoped to >= since (the moment time-tracking began) so piece counts cover
    # the same window as the accumulated hours — legacy pieces are excluded.
    rows = conn.execute(
        "SELECT date(seen_at, 'unixepoch', 'localtime') AS day, "
        "COUNT(*) AS pieces_seen, "
        "SUM(CASE WHEN classification_status = 'classified' THEN 1 ELSE 0 END) AS pieces_classified, "
        "SUM(CASE WHEN bin_x IS NOT NULL THEN 1 ELSE 0 END) AS pieces_distributed "
        "FROM piece_records WHERE seen_at IS NOT NULL AND seen_at >= ? "
        "GROUP BY day",
        (since,),
    ).fetchall()
    by_day: dict[str, dict[str, int]] = {}
    for r in rows:
        if r["day"] is None:
            continue
        by_day[r["day"]] = {
            "pieces_seen": int(r["pieces_seen"] or 0),
            "pieces_classified": int(r["pieces_classified"] or 0),
            "pieces_distributed": int(r["pieces_distributed"] or 0),
        }
    return by_day


def _timeByDay(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    rows = conn.execute(
        "SELECT date(hour_start, 'unixepoch', 'localtime') AS day, "
        "SUM(seconds_powered) AS seconds_powered, "
        "SUM(seconds_sorted) AS seconds_sorted "
        "FROM lifetime_hourly GROUP BY day"
    ).fetchall()
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["day"] is None:
            continue
        by_day[r["day"]] = {
            "seconds_powered": float(r["seconds_powered"] or 0.0),
            "seconds_sorted": float(r["seconds_sorted"] or 0.0),
        }
    return by_day


def getOverview(*, daily_days: int = 30) -> dict[str, Any]:
    daily_days = max(1, min(daily_days, 365))
    with _connection() as conn:
        totals = conn.execute(
            "SELECT "
            "COALESCE(SUM(seconds_powered), 0) AS seconds_powered, "
            "COALESCE(SUM(seconds_sorted), 0) AS seconds_sorted, "
            "MIN(hour_start) AS first_hour, "
            "MAX(hour_start) AS last_hour "
            "FROM lifetime_hourly"
        ).fetchone()
        # Piece counts are scoped to the tracking window so they line up with the
        # accumulated hours (and PPM is real). The window opens at the first hour
        # bucket we ever flushed; before any tracking exists, nothing is in scope.
        tracking_start = float(totals["first_hour"]) if totals["first_hour"] is not None else None
        if tracking_start is None:
            pieces = {"pieces_seen": 0, "pieces_classified": 0, "pieces_distributed": 0}
        else:
            pieces = conn.execute(
                "SELECT "
                "COUNT(*) AS pieces_seen, "
                "SUM(CASE WHEN classification_status = 'classified' THEN 1 ELSE 0 END) AS pieces_classified, "
                "SUM(CASE WHEN bin_x IS NOT NULL THEN 1 ELSE 0 END) AS pieces_distributed "
                "FROM piece_records WHERE seen_at >= ?",
                (tracking_start,),
            ).fetchone()
        # Best sustained throughput: the busiest single hour by distributed PPM,
        # ignoring hours with under a minute of sorting so a stray piece in an
        # almost-idle hour can't masquerade as a record rate. Piece counts are
        # grouped per hour bucket in ONE pass over piece_records and joined to
        # the hour rows — the old correlated per-bucket COUNT subquery re-scanned
        # the index once per lifetime hour and dominated this endpoint's latency.
        best = conn.execute(
            "SELECT MAX(pc.cnt * 60.0 / h.seconds_sorted) AS best_ppm "
            "FROM lifetime_hourly h "
            "JOIN ("
            "SELECT CAST(seen_at / ? AS INTEGER) * ? AS hour_start, COUNT(*) AS cnt "
            "FROM piece_records "
            "WHERE bin_x IS NOT NULL AND seen_at IS NOT NULL AND seen_at >= 0 "
            "GROUP BY 1"
            ") pc ON pc.hour_start = h.hour_start "
            "WHERE h.seconds_sorted >= 60",
            (SECONDS_PER_HOUR, SECONDS_PER_HOUR),
        ).fetchone()
        time_by_day = _timeByDay(conn)
        pieces_by_day = _piecesByDay(conn, tracking_start) if tracking_start is not None else {}

    seconds_sorted = float(totals["seconds_sorted"] or 0.0)
    seconds_powered = float(totals["seconds_powered"] or 0.0)
    pieces_distributed = int(pieces["pieces_distributed"] or 0)
    overall_ppm = (pieces_distributed * 60.0 / seconds_sorted) if seconds_sorted > 0 else 0.0

    all_days = sorted(set(time_by_day) | set(pieces_by_day), reverse=True)[:daily_days]
    daily = []
    for day in all_days:
        t = time_by_day.get(day, {})
        p = pieces_by_day.get(day, {})
        daily.append({
            "day": day,
            "seconds_powered": t.get("seconds_powered", 0.0),
            "seconds_sorted": t.get("seconds_sorted", 0.0),
            "pieces_seen": p.get("pieces_seen", 0),
            "pieces_classified": p.get("pieces_classified", 0),
            "pieces_distributed": p.get("pieces_distributed", 0),
        })

    return {
        "seconds_sorted": seconds_sorted,
        "seconds_powered": seconds_powered,
        "pieces_seen": int(pieces["pieces_seen"] or 0),
        "pieces_classified": int(pieces["pieces_classified"] or 0),
        "pieces_distributed": pieces_distributed,
        "overall_ppm": overall_ppm,
        "best_hour_ppm": float(best["best_ppm"] or 0.0) if best else 0.0,
        "active_days": len([d for d in daily if d["seconds_powered"] > 0 or d["pieces_seen"] > 0]),
        "first_hour": totals["first_hour"],
        "last_hour": totals["last_hour"],
        "daily": daily,
    }
