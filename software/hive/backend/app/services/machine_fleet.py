import threading
import time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.machine_piece import MachinePiece

# Two pieces more than this many seconds apart are treated as separate sorting
# sessions, so the gap between them is NOT counted as active time. Tunable
# against a machine whose real /records numbers we know.
ACTIVE_GAP_IDLE_S = 60.0

_CACHE_TTL_S = 60.0
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _active_seconds_by_machine(db: Session) -> dict[str, float]:
    """Sum the gaps between consecutive pieces per machine, ignoring idle gaps.

    Derived active sorting time — we intentionally don't sync the machine's real
    powered/sorted seconds, so we infer activity from piece-timestamp density.
    """
    # Postgres: one windowed pass. Other dialects (sqlite test DB): compute in
    # Python since test datasets are tiny.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        result = db.execute(
            text(
                """
                WITH g AS (
                    SELECT machine_id,
                           EXTRACT(EPOCH FROM (
                               seen_at - LAG(seen_at) OVER (
                                   PARTITION BY machine_id ORDER BY seen_at, local_id))) AS gap
                    FROM machine_pieces
                    WHERE seen_at IS NOT NULL)
                SELECT machine_id,
                       COALESCE(SUM(CASE WHEN gap > 0 AND gap <= :idle THEN gap ELSE 0 END), 0) AS active
                FROM g GROUP BY machine_id
                """
            ),
            {"idle": ACTIVE_GAP_IDLE_S},
        )
        return {str(mid): float(active) for mid, active in result}

    active: dict[str, float] = {}
    prev_mid = None
    prev_seen = None
    rows = (
        db.query(MachinePiece.machine_id, MachinePiece.seen_at)
        .filter(MachinePiece.seen_at.isnot(None))
        .order_by(MachinePiece.machine_id, MachinePiece.seen_at, MachinePiece.local_id)
        .all()
    )
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


def _compute(db: Session) -> dict[str, dict[str, Any]]:
    agg = (
        db.query(
            MachinePiece.machine_id,
            func.count().label("pieces_seen"),
            func.count().filter(MachinePiece.bin_x.isnot(None)).label("distributed"),
            func.count().filter(MachinePiece.classification_status == "classified").label("classified"),
            func.count(func.distinct(MachinePiece.part_id)).label("unique_parts"),
            func.count(func.distinct(MachinePiece.color_id)).label("unique_colors"),
            func.min(MachinePiece.seen_at).label("first_seen"),
            func.max(MachinePiece.seen_at).label("last_seen"),
        )
        .group_by(MachinePiece.machine_id)
        .all()
    )
    active_by_machine = _active_seconds_by_machine(db)

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
            "first_seen": r.first_seen.isoformat() if r.first_seen else None,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "active_seconds": active_s,
            "overall_ppm": overall_ppm,
            "ontime_pct": ontime_pct,
        }
    return result


def get_fleet_stats(db: Session) -> dict[str, dict[str, Any]]:
    now = time.monotonic()
    with _cache_lock:
        if _cache["value"] is not None and (now - _cache["at"]) < _CACHE_TTL_S:
            return _cache["value"]
    value = _compute(db)
    with _cache_lock:
        _cache["at"] = time.monotonic()
        _cache["value"] = value
    return value
