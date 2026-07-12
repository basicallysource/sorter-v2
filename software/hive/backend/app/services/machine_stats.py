"""Per-machine dashboard stats: computation, persistent cache, refresh worker.

Two families of metrics per machine:
  * piece-derived  — pieces_seen, distributed, PPM, on-time %, unique parts/colors
    (from machine_pieces; active sorting time inferred from piece-timestamp density)
  * sample-derived — total/accepted samples, sessions, set-progress parts
    (from samples / upload_sessions / machine_set_progress)

Recomputing these over the whole fleet on every request was the load source on
the admin machines page. Instead a daemon thread refreshes one row per machine
into machine_stats_cache hourly; the API reads those rows. Single-machine
overviews lazily compute + cache on a miss so a brand-new machine isn't blank
until the next scheduled pass.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_stats_cache import MachineStatsCache

logger = logging.getLogger(__name__)

# Two pieces more than this many seconds apart are treated as separate sorting
# sessions, so the gap between them is NOT counted as active time. Tunable
# against a machine whose real /records numbers we know.
ACTIVE_GAP_IDLE_S = 60.0

# Fields carried through the cache row, in the shape the API serves. Date fields
# are handled separately so we can store datetimes but serve ISO strings.
_NUMERIC_FIELDS = (
    "pieces_seen",
    "distributed",
    "classified",
    "unique_parts",
    "unique_colors",
    "active_seconds",
    "overall_ppm",
    "ontime_pct",
    "total_samples",
    "accepted_samples",
    "total_sessions",
    "parts_found",
    "parts_needed",
)
_DATE_FIELDS = ("first_seen", "last_seen", "first_capture", "last_capture")


def _empty_stats() -> dict[str, Any]:
    stats: dict[str, Any] = {f: 0 for f in _NUMERIC_FIELDS}
    stats["active_seconds"] = 0.0
    stats["overall_ppm"] = 0.0
    stats["ontime_pct"] = 0.0
    for f in _DATE_FIELDS:
        stats[f] = None
    return stats


def _active_seconds_by_machine(db: Session, machine_ids: list[Any] | None = None) -> dict[str, float]:
    """Sum the gaps between consecutive pieces per machine, ignoring idle gaps."""
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        filter_sql = ""
        params: dict[str, Any] = {"idle": ACTIVE_GAP_IDLE_S}
        if machine_ids is not None:
            # Cast the uuid column to text — the bound ids are strings, and
            # Postgres has no uuid = text operator for the ANY() comparison.
            filter_sql = "AND machine_id::text = ANY(:mids)"
            params["mids"] = [str(m) for m in machine_ids]
        result = db.execute(
            text(
                f"""
                WITH g AS (
                    SELECT machine_id,
                           EXTRACT(EPOCH FROM (
                               seen_at - LAG(seen_at) OVER (
                                   PARTITION BY machine_id ORDER BY seen_at, local_id))) AS gap
                    FROM machine_pieces
                    WHERE seen_at IS NOT NULL {filter_sql})
                SELECT machine_id,
                       COALESCE(SUM(CASE WHEN gap > 0 AND gap <= :idle THEN gap ELSE 0 END), 0) AS active
                FROM g GROUP BY machine_id
                """
            ),
            params,
        )
        return {str(mid): float(active) for mid, active in result}

    active: dict[str, float] = {}
    prev_mid = None
    prev_seen = None
    query = db.query(MachinePiece.machine_id, MachinePiece.seen_at).filter(MachinePiece.seen_at.isnot(None))
    if machine_ids is not None:
        query = query.filter(MachinePiece.machine_id.in_(machine_ids))
    rows = query.order_by(MachinePiece.machine_id, MachinePiece.seen_at, MachinePiece.local_id).all()
    for mid, seen_at in rows:
        mid_str = str(mid)
        active.setdefault(mid_str, 0.0)
        if prev_mid == mid_str and prev_seen is not None:
            gap = (seen_at - prev_seen).total_seconds()
            if 0 < gap <= ACTIVE_GAP_IDLE_S:
                active[mid_str] += gap
        prev_mid = mid_str
        prev_seen = seen_at
    return active


def _compute_piece_stats(db: Session, machine_ids: list[Any] | None = None) -> dict[str, dict[str, Any]]:
    query = db.query(
        MachinePiece.machine_id,
        func.count().label("pieces_seen"),
        func.count().filter(MachinePiece.bin_x.isnot(None)).label("distributed"),
        func.count().filter(MachinePiece.classification_status == "classified").label("classified"),
        func.count(func.distinct(MachinePiece.part_id)).label("unique_parts"),
        func.count(func.distinct(MachinePiece.color_id)).label("unique_colors"),
        func.min(MachinePiece.seen_at).label("first_seen"),
        func.max(MachinePiece.seen_at).label("last_seen"),
    )
    if machine_ids is not None:
        query = query.filter(MachinePiece.machine_id.in_(machine_ids))
    agg = query.group_by(MachinePiece.machine_id).all()
    active_by_machine = _active_seconds_by_machine(db, machine_ids)

    result: dict[str, dict[str, Any]] = {}
    for r in agg:
        mid = str(r.machine_id)
        active_s = active_by_machine.get(mid, 0.0)
        distributed = r.distributed or 0
        overall_ppm = (distributed * 60.0 / active_s) if active_s > 0 else 0.0
        span_s = (
            (r.last_seen - r.first_seen).total_seconds()
            if r.first_seen and r.last_seen
            else 0.0
        )
        ontime_pct = (active_s / span_s * 100.0) if span_s > 0 else 0.0
        result[mid] = {
            "pieces_seen": r.pieces_seen or 0,
            "distributed": distributed,
            "classified": r.classified or 0,
            "unique_parts": r.unique_parts or 0,
            "unique_colors": r.unique_colors or 0,
            "first_seen": r.first_seen,
            "last_seen": r.last_seen,
            "active_seconds": active_s,
            "overall_ppm": overall_ppm,
            "ontime_pct": ontime_pct,
        }
    return result


def _compute_sample_stats(db: Session, machine_ids: list[Any] | None = None) -> dict[str, dict[str, Any]]:
    from app.models.sample import Sample
    from app.models.upload_session import UploadSession
    from app.models.machine_set_progress import MachineSetProgress

    def _scoped(query, col):
        return query.filter(col.in_(machine_ids)) if machine_ids is not None else query

    sample_rows = _scoped(
        db.query(
            Sample.machine_id,
            func.count(Sample.id).label("total_samples"),
            func.count(Sample.id).filter(Sample.review_status == "accepted").label("accepted_samples"),
            func.min(Sample.captured_at).label("first_capture"),
            func.max(Sample.captured_at).label("last_capture"),
        ),
        Sample.machine_id,
    ).group_by(Sample.machine_id).all()
    sample_map = {str(r.machine_id): r for r in sample_rows}

    session_rows = _scoped(
        db.query(UploadSession.machine_id, func.count(UploadSession.id).label("total_sessions")),
        UploadSession.machine_id,
    ).group_by(UploadSession.machine_id).all()
    session_map = {str(r.machine_id): r.total_sessions for r in session_rows}

    progress_rows = _scoped(
        db.query(
            MachineSetProgress.machine_id,
            func.sum(MachineSetProgress.quantity_found).label("parts_found"),
            func.sum(MachineSetProgress.quantity_needed).label("parts_needed"),
        ),
        MachineSetProgress.machine_id,
    ).group_by(MachineSetProgress.machine_id).all()
    progress_map = {str(r.machine_id): r for r in progress_rows}

    result: dict[str, dict[str, Any]] = {}
    keys = set(sample_map) | set(session_map) | set(progress_map)
    for mid in keys:
        sr = sample_map.get(mid)
        pr = progress_map.get(mid)
        result[mid] = {
            "total_samples": sr.total_samples if sr else 0,
            "accepted_samples": sr.accepted_samples if sr else 0,
            "first_capture": sr.first_capture if sr else None,
            "last_capture": sr.last_capture if sr else None,
            "total_sessions": session_map.get(mid, 0),
            "parts_found": int(pr.parts_found) if pr and pr.parts_found else 0,
            "parts_needed": int(pr.parts_needed) if pr and pr.parts_needed else 0,
        }
    return result


def compute_stats(db: Session, machine_ids: list[Any] | None = None) -> dict[str, dict[str, Any]]:
    """Merged piece + sample stats, one entry per machine.

    When machine_ids is None every machine gets a row (so the cache stays
    complete). Date fields are datetimes here; serialize before serving.
    """
    if machine_ids is None:
        ids = [mid for (mid,) in db.query(Machine.id).all()]
    else:
        ids = list(machine_ids)

    piece_stats = _compute_piece_stats(db, ids)
    sample_stats = _compute_sample_stats(db, ids)

    merged: dict[str, dict[str, Any]] = {}
    for mid in ids:
        mid_str = str(mid)
        stats = _empty_stats()
        stats.update(piece_stats.get(mid_str, {}))
        stats.update(sample_stats.get(mid_str, {}))
        merged[mid_str] = stats
    return merged


def refresh_cache(db: Session, machine_ids: list[Any] | None = None) -> int:
    """Recompute and upsert cache rows. Returns the number of machines refreshed."""
    stats = compute_stats(db, machine_ids)
    now = datetime.now(timezone.utc)
    key_uuids = [uuid_mod.UUID(k) for k in stats.keys()]
    existing = {
        str(row.machine_id): row
        for row in db.query(MachineStatsCache)
        .filter(MachineStatsCache.machine_id.in_(key_uuids))
        .all()
    } if stats else {}

    for mid, values in stats.items():
        row = existing.get(mid)
        if row is None:
            row = MachineStatsCache(machine_id=uuid_mod.UUID(mid))
            db.add(row)
        for field in _NUMERIC_FIELDS + _DATE_FIELDS:
            setattr(row, field, values[field])
        row.computed_at = now
    db.commit()
    return len(stats)


def _serialize(values: dict[str, Any], computed_at: datetime | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in _NUMERIC_FIELDS:
        out[f] = values[f]
    for f in _DATE_FIELDS:
        v = values.get(f)
        out[f] = v.isoformat() if isinstance(v, datetime) else v
    out["computed_at"] = computed_at.isoformat() if isinstance(computed_at, datetime) else None
    return out


def _row_to_values(row: MachineStatsCache) -> dict[str, Any]:
    return {f: getattr(row, f) for f in _NUMERIC_FIELDS + _DATE_FIELDS}


def get_fleet_stats(db: Session) -> dict[str, dict[str, Any]]:
    """Piece-derived stats for every cached machine, keyed by machine id.

    Shape matches the admin fleet table (FleetMachineStats). Reads the cache
    only — machines missing a row (never refreshed) fall back to zeros via the
    frontend's EMPTY default.
    """
    rows = db.query(MachineStatsCache).all()
    fleet_fields = (
        "pieces_seen", "distributed", "classified", "unique_parts", "unique_colors",
        "active_seconds", "overall_ppm", "ontime_pct",
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = {f: getattr(row, f) for f in fleet_fields}
        entry["first_seen"] = row.first_seen.isoformat() if row.first_seen else None
        entry["last_seen"] = row.last_seen.isoformat() if row.last_seen else None
        result[str(row.machine_id)] = entry
    return result


def get_machine_stats(db: Session, machine_id: Any) -> dict[str, Any]:
    """Full serialized stats for one machine. Lazily computes + caches on a miss."""
    row = db.query(MachineStatsCache).filter(MachineStatsCache.machine_id == machine_id).first()
    if row is not None:
        return _serialize(_row_to_values(row), row.computed_at)
    # Cache miss (machine registered after the last refresh) — compute just this
    # one and persist so subsequent loads are cheap.
    try:
        refresh_cache(db, [machine_id])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("machine_stats lazy refresh failed for %s: %s", machine_id, exc)
        db.rollback()
    row = db.query(MachineStatsCache).filter(MachineStatsCache.machine_id == machine_id).first()
    if row is not None:
        return _serialize(_row_to_values(row), row.computed_at)
    return _serialize(_empty_stats(), None)


class MachineStatsWorker:
    """Daemon thread that refreshes machine_stats_cache on a fixed cadence."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._start_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "last_run_at": None,
            "last_run_machines": 0,
            "last_run_duration_s": None,
            "last_error": None,
            "total_runs": 0,
        }

    def start(self) -> None:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="machine-stats-worker")
            self._thread.start()
        self._update_state(running=True)

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._update_state(running=False)

    def wake(self) -> None:
        """Ask the loop to run a refresh pass as soon as possible."""
        self._wake_event.set()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            snapshot = dict(self._state)
        snapshot["interval_s"] = self._interval_s()
        return snapshot

    def _interval_s(self) -> float:
        return max(60.0, float(settings.MACHINE_STATS_REFRESH_INTERVAL_MINUTES) * 60.0)

    def _loop(self) -> None:
        logger.info("MachineStatsWorker: started")
        # Prime the cache on boot so the first dashboard load is already warm.
        self._run_one_pass()
        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=self._interval_s())
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            self._run_one_pass()
        self._update_state(running=False)
        logger.info("MachineStatsWorker: stopped")

    def _run_one_pass(self) -> None:
        started = time.monotonic()
        db = SessionLocal()
        try:
            count = refresh_cache(db)
            # Same pass also maintains the per-day analytics substrate.
            from app.services import analytics

            analytics.refresh_daily_stats(db)
            self._update_state(
                last_run_at=datetime.now(timezone.utc).isoformat(),
                last_run_machines=count,
                last_run_duration_s=round(time.monotonic() - started, 3),
                last_error=None,
                increment_runs=1,
            )
            logger.info("MachineStatsWorker: refreshed %d machines in %.2fs", count, time.monotonic() - started)
        except Exception as exc:
            logger.exception("MachineStatsWorker pass crashed: %s", exc)
            db.rollback()
            self._update_state(last_error=str(exc))
        finally:
            db.close()

    def _update_state(self, **kwargs: Any) -> None:
        with self._state_lock:
            if "running" in kwargs:
                self._state["running"] = bool(kwargs.pop("running"))
            if "increment_runs" in kwargs:
                self._state["total_runs"] += int(kwargs.pop("increment_runs"))
            for key, value in kwargs.items():
                self._state[key] = value


_INSTANCE: MachineStatsWorker | None = None
_INSTANCE_LOCK = threading.Lock()


def get_machine_stats_worker() -> MachineStatsWorker:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = MachineStatsWorker()
    return _INSTANCE


__all__ = [
    "compute_stats",
    "refresh_cache",
    "get_fleet_stats",
    "get_machine_stats",
    "MachineStatsWorker",
    "get_machine_stats_worker",
]
