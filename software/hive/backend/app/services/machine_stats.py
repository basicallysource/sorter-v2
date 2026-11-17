"""Per-machine stats: computation, persistent cache, refresh worker.

**This module owns the only fleet-scale aggregation in the app.** Nothing on a
request path may scan machine_pieces; `services/analytics.py` folds the rows
this writes, and every stats surface reads that fold. See `analytics` for why.

Three families of metrics per machine:
  * piece-derived  — pieces_seen, distributed, PPM, on-time %, unique parts/colors
    (from machine_pieces; active sorting time inferred from piece-timestamp density)
  * sample-derived — total/accepted samples, sessions, set-progress parts
    (from samples / upload_sessions / machine_set_progress)
  * distributions  — the whole per-machine part / color / status maps, which are
    what let an arbitrary set of machines be answered without touching pieces.

Recomputing these over the whole fleet on every request was the load source on
the admin machines page, and later on the public one. Instead a worker refreshes
one row per machine into machine_stats_cache; the API reads those rows.

**A pass reads what changed, not the fleet's history.** Rescanning every piece
and channel crop each pass ran past the worker's statement limit once the fleet
had two million pieces and fifty million crops, and the cache froze
(2026-11-16). Now:
  * piece numbers come from per machine-day partial answers that triggers mark
    stale when pieces change (`services/piece_days.py`); a pass rebuilds the
    marked days and folds the machine's day rows;
  * channel crops are counted by triggers into machine_channel_crop_deltas,
    which a pass adds to the count and deletes;
  * the sample counts are grouped scans of narrow indexes on samples (a few
    thousand samples a day, not a million crops).
A machine is counted in full once, the first time the worker sees it after the
triggers exist (`incremental_since`). Single-machine overviews compute and
cache on a miss so a brand-new machine isn't blank until the next pass.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import STATEMENT_TIMEOUT_KEY, SessionLocal
from app.models.machine import Machine
from app.models.machine_channel_crop import MachineChannelCrop, MachineChannelCropDelta
from app.models.machine_piece import MachinePiece
from app.models.machine_stats_cache import MachineStatsCache
from app.services import piece_days
from app.services.periodic import PeriodicWorker
from app.services.piece_days import ACTIVE_GAP_IDLE_S  # noqa: F401  (fleet_records reads it here)

logger = logging.getLogger(__name__)

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
    "unreviewed_samples",
    "in_review_samples",
    "rejected_samples",
    "conflict_samples",
    "total_sessions",
    "parts_found",
    "parts_needed",
    "channel_crops",
)
_DATE_FIELDS = ("first_seen", "last_seen", "first_capture", "last_capture")
_PIECE_FIELDS = (
    "pieces_seen", "distributed", "classified", "unique_parts", "unique_colors",
    "first_seen", "last_seen", "active_seconds", "overall_ppm", "ontime_pct",
)
_SAMPLE_FIELDS = (
    "total_samples", "accepted_samples", "unreviewed_samples", "in_review_samples", "rejected_samples",
    "conflict_samples", "first_capture", "last_capture", "total_sessions", "parts_found", "parts_needed",
)


def _empty_distributions() -> dict[str, Any]:
    return {"status": {}, "parts": {}, "colors": {}}


def _empty_stats() -> dict[str, Any]:
    stats: dict[str, Any] = {f: 0 for f in _NUMERIC_FIELDS}
    stats["active_seconds"] = 0.0
    stats["overall_ppm"] = 0.0
    stats["ontime_pct"] = 0.0
    for f in _DATE_FIELDS:
        stats[f] = None
    stats["distributions"] = _empty_distributions()
    return stats


def _compute_sample_stats(db: Session, machine_ids: list[Any] | None = None) -> dict[str, dict[str, Any]]:
    from app.models.sample import Sample
    from app.models.upload_session import UploadSession
    from app.models.machine_set_progress import MachineSetProgress

    def _scoped(query, col):
        return query.filter(col.in_(machine_ids)) if machine_ids is not None else query

    # count(*), never count(Sample.id): the id is not in the narrow indexes
    # these read, and asking for it sends each query to the wide table.
    sample_rows = _scoped(
        db.query(
            Sample.machine_id,
            func.count().label("total_samples"),
            func.count().filter(Sample.review_status == "accepted").label("accepted_samples"),
            func.count().filter(Sample.review_status == "unreviewed").label("unreviewed_samples"),
            func.count().filter(Sample.review_status == "in_review").label("in_review_samples"),
            func.count().filter(Sample.review_status == "rejected").label("rejected_samples"),
            func.count().filter(Sample.review_status == "conflict").label("conflict_samples"),
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

    # The sources and capture reasons the Channel samples filters offer, with
    # their counts, per machine; archived samples are not offered.
    source_rows = _scoped(
        db.query(Sample.machine_id, Sample.source_role, func.count())
        .filter(Sample.archived_at.is_(None), Sample.source_role.isnot(None)),
        Sample.machine_id,
    ).group_by(Sample.machine_id, Sample.source_role).all()
    reason_rows = _scoped(
        db.query(Sample.machine_id, Sample.capture_reason, func.count())
        .filter(Sample.archived_at.is_(None), Sample.capture_reason.isnot(None)),
        Sample.machine_id,
    ).group_by(Sample.machine_id, Sample.capture_reason).all()
    sources: dict[str, dict[str, int]] = {}
    reasons: dict[str, dict[str, int]] = {}
    for mid, value, count in source_rows:
        if value:
            sources.setdefault(str(mid), {})[value] = int(count)
    for mid, value, count in reason_rows:
        if value:
            reasons.setdefault(str(mid), {})[value] = int(count)

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
    keys = set(sample_map) | set(session_map) | set(progress_map) | set(sources) | set(reasons)
    for mid in keys:
        sr = sample_map.get(mid)
        pr = progress_map.get(mid)
        result[mid] = {
            "total_samples": sr.total_samples if sr else 0,
            "accepted_samples": sr.accepted_samples if sr else 0,
            "unreviewed_samples": sr.unreviewed_samples if sr else 0,
            "in_review_samples": sr.in_review_samples if sr else 0,
            "rejected_samples": sr.rejected_samples if sr else 0,
            "conflict_samples": sr.conflict_samples if sr else 0,
            "first_capture": sr.first_capture if sr else None,
            "last_capture": sr.last_capture if sr else None,
            "total_sessions": session_map.get(mid, 0),
            "parts_found": int(pr.parts_found) if pr and pr.parts_found else 0,
            "parts_needed": int(pr.parts_needed) if pr and pr.parts_needed else 0,
            "sample_sources": sources.get(mid, {}),
            "sample_capture_reasons": reasons.get(mid, {}),
        }
    return result


def _empty_sample_stats() -> dict[str, Any]:
    return {
        **{name: 0 for name in _SAMPLE_FIELDS},
        "first_capture": None,
        "last_capture": None,
        "sample_sources": {},
        "sample_capture_reasons": {},
    }


def _compute_control_data(db: Session, machine_ids: list[Any]) -> dict[str, dict[str, Any]]:
    """Each machine's control-data segments summed per combination of modes,
    for the admin inventory to add up instead of reading every segment."""
    from app.services.control_data import segment_rows, summarize_segments

    by_machine: dict[str, list] = {}
    for row in segment_rows(db, machine_ids):
        by_machine.setdefault(str(row.machine_id), []).append(row)
    return {mid: summarize_segments(rows) for mid, rows in by_machine.items()}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # sqlite (the tests) hands datetimes back naive; every stored time is UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# What the last refresh did, for the worker's status.
LAST_PASS: dict[str, int] = {}

# A new row's watermark: until its pieces are folded, piece_total counts every
# piece the machine has as arriving after it.
_NEVER = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _cache_rows(db: Session, ids: list[Any]) -> dict[str, MachineStatsCache]:
    rows: dict[str, MachineStatsCache] = {}
    for chunk in (ids[i : i + 500] for i in range(0, len(ids), 500)):
        for row in (
            db.query(MachineStatsCache)
            .filter(MachineStatsCache.machine_id.in_(chunk))
            .populate_existing()
        ):
            rows[str(row.machine_id)] = row
    return rows


def _unbounded(db: Session) -> None:
    """Lift the statement limit for the rest of this transaction, for the one
    full count a machine ever gets. Not in a request, which keeps its own."""
    if db.get_bind().dialect.name == "postgresql" and not db.info.get(STATEMENT_TIMEOUT_KEY):
        db.execute(text("SET LOCAL statement_timeout = 0"))


def _count_crops(db: Session, machine_id: Any) -> int:
    """The machine's channel crops counted in full, with the deltas that count
    already holds removed, in one snapshot: deltas written after it stay for
    the next pass to add."""
    if db.get_bind().dialect.name == "postgresql":
        return int(
            db.execute(
                text(
                    "WITH taken AS (DELETE FROM machine_channel_crop_deltas WHERE machine_id = :m RETURNING n) "
                    "SELECT count(*) FROM machine_channel_crops WHERE machine_id = :m"
                ),
                {"m": machine_id},
            ).scalar()
            or 0
        )
    db.execute(delete(MachineChannelCropDelta).where(MachineChannelCropDelta.machine_id == machine_id))
    return int(
        db.execute(select(func.count()).select_from(MachineChannelCrop).where(MachineChannelCrop.machine_id == machine_id)).scalar()
        or 0
    )


def _seed(db: Session, machine_id: Any) -> None:
    """Count a machine in full, once: mark every day it has pieces on (the
    piece pass that follows builds them) and count its crops. Commits."""
    try:
        piece_days.lock_machine(db, machine_id)
        _unbounded(db)
        row = db.get(MachineStatsCache, machine_id, populate_existing=True)
        if row is None:
            row = MachineStatsCache(machine_id=machine_id, **{f: v for f, v in _empty_stats().items() if f in _NUMERIC_FIELDS + _DATE_FIELDS})
            row.distributions = _empty_distributions()
            row.control_data = {}
            row.computed_at = _NEVER
            db.add(row)
        if row.incremental_since is not None:
            db.rollback()
            return
        days = piece_days.seed(db, machine_id)
        row.channel_crops = _count_crops(db, machine_id)
        row.incremental_since = _now()
        db.commit()
        logger.info("machine stats: counted %s in full (%d days of pieces, %d crops)", machine_id, days, row.channel_crops)
    except Exception:
        db.rollback()
        raise


def _refresh_pieces(db: Session, machine_id: Any) -> int:
    """Rebuild the machine's marked piece days and write its piece numbers to
    its cache row. Commits. Returns the days rebuilt."""
    try:
        piece_days.lock_machine(db, machine_id)
        # Pieces that reach Hive from here on are counted live (piece_total)
        # until the next pass, so the watermark is taken before the marks.
        taken_at = _now()
        result = piece_days.refresh_machine(db, machine_id)
        if result is None:
            db.rollback()
            return 0
        folded, days = result
        row = db.get(MachineStatsCache, machine_id, populate_existing=True)
        if row is not None:
            for name, value in folded.as_stats().items():
                setattr(row, name, value)
            row.distributions = {**(row.distributions or {}), **folded.distributions}
            row.computed_at = taken_at
        db.commit()
        return days
    except Exception:
        db.rollback()
        raise


def _add_crop_deltas(db: Session, rows: dict[str, MachineStatsCache]) -> int:
    """Add the crop deltas of counted machines to their counts and delete them;
    drop those of machines that are gone. The caller commits."""
    counted = [row.machine_id for row in rows.values() if row.incremental_since is not None]
    added: dict[str, int] = {}
    for chunk in (counted[i : i + 500] for i in range(0, len(counted), 500)):
        for mid, n in db.execute(
            delete(MachineChannelCropDelta)
            .where(MachineChannelCropDelta.machine_id.in_(chunk))
            .returning(MachineChannelCropDelta.machine_id, MachineChannelCropDelta.n)
        ):
            added[str(mid)] = added.get(str(mid), 0) + int(n)
    for mid, n in added.items():
        rows[mid].channel_crops = int(rows[mid].channel_crops or 0) + n
    db.execute(
        delete(MachineChannelCropDelta).where(MachineChannelCropDelta.machine_id.notin_(select(Machine.id)))
    )
    return sum(added.values())


def refresh_cache(db: Session, machine_ids: list[Any] | None = None) -> int:
    """Bring cache rows up to date. Returns the number of machines refreshed.

    With machine_ids None every machine gets a row, so the cache stays complete.
    """
    started = _now()
    known = [mid for (mid,) in db.query(Machine.id).all()]
    if machine_ids is None:
        ids = known
    else:
        wanted = {str(m) for m in machine_ids}
        ids = [mid for mid in known if str(mid) in wanted]
    if not ids:
        return 0

    # One machine that fails (a statement cancelled, a bad row) is logged and
    # left for the next pass; it never holds back the others' numbers.
    failed: list[str] = []
    rows = _cache_rows(db, ids)
    for mid in ids:
        row = rows.get(str(mid))
        if row is None or row.incremental_since is None:
            try:
                _seed(db, mid)
            except Exception:
                logger.exception("machine stats: counting %s in full failed", mid)
                failed.append(str(mid))

    marked = piece_days.marked_machines(db)
    days = 0
    for mid in ids:
        if mid in marked and str(mid) not in failed:
            try:
                days += _refresh_pieces(db, mid)
            except Exception:
                logger.exception("machine stats: rebuilding %s's piece days failed", mid)
                failed.append(str(mid))
    if machine_ids is None:
        piece_days.forget_gone_machines(db, set(known))
        db.commit()

    # Samples, crops and control data, for every machine in one transaction.
    rows = _cache_rows(db, ids)
    ids = [mid for mid in ids if str(mid) in rows]
    samples = _compute_sample_stats(db, ids)
    control_data = _compute_control_data(db, ids)
    crops_added = _add_crop_deltas(db, rows)
    for mid in ids:
        key = str(mid)
        row = rows[key]
        values = {**_empty_sample_stats(), **samples.get(key, {})}
        for name in _SAMPLE_FIELDS:
            setattr(row, name, values[name])
        row.distributions = {
            **_empty_distributions(),
            **(row.distributions or {}),
            "sample_sources": values["sample_sources"],
            "sample_capture_reasons": values["sample_capture_reasons"],
        }
        row.control_data = control_data.get(key, {})
        # A machine with no piece days marked had no pieces arrive since its
        # last pass: its numbers are current as of the start of this one. One
        # that failed keeps its watermark, so the live count still adds the
        # pieces its numbers lack.
        if key not in failed and (row.computed_at is None or _aware(row.computed_at) < started):
            row.computed_at = started
    db.commit()
    LAST_PASS.clear()
    LAST_PASS.update({"piece_days_rebuilt": days, "crops_added": crops_added, "machines_failed": len(failed)})
    logger.info(
        "machine stats: %d machines, %d piece days rebuilt, %d crops added, %d failed",
        len(ids), days, crops_added, len(failed),
    )
    return len(ids)


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


def piece_total(db: Session, machine_id: Any) -> int:
    """How many pieces a machine has synced: the cached count plus the pieces
    that reached Hive since it was computed (an index range on (machine_id,
    created_at) over the last hour or so). A machine not cached yet is counted
    whole, which is cheap because it is new."""
    row = (
        db.query(MachineStatsCache.pieces_seen, MachineStatsCache.computed_at)
        .filter(MachineStatsCache.machine_id == machine_id)
        .first()
    )
    newer = db.query(func.count()).select_from(MachinePiece).filter(MachinePiece.machine_id == machine_id)
    if row is None:
        return int(newer.scalar() or 0)
    return int(row.pieces_seen or 0) + int(newer.filter(MachinePiece.created_at >= row.computed_at).scalar() or 0)


def channel_crop_total(db: Session, machine_id: Any) -> int:
    """How many upstream channel crops a machine had at the stats worker's
    last pass."""
    return int(
        db.query(MachineStatsCache.channel_crops).filter(MachineStatsCache.machine_id == machine_id).scalar() or 0
    )


def refresh_all(db: Session) -> int:
    """One full pass over a session: per-machine cache (and with it the daily
    table, kept from the same machine-days), then the sample tables.

    This is the ONLY place in the app that aggregates over machine_pieces at
    fleet scale. Everything served to a request is a fold over what this
    writes, so anything that wants fresh numbers — the worker, a test, an admin
    forcing a rebuild — calls this rather than growing its own copy.
    """
    count = refresh_cache(db)
    # Same pass also maintains the weekly sample counts the diversity overview
    # adds up, and the datasets' counts per machine (recounted, for samples
    # deleted since they were recorded).
    from app.services import model_datasets, sample_diversity

    sample_diversity.refresh(db)
    model_datasets.recount(db)
    return count


def warn_if_disk_low(path: str = "/") -> float | None:
    """Alert the operator, once a day, while the disk has less than
    DISK_ALERT_FREE_PCT free. In the worker's container the root is the host's
    disk Docker keeps its data on, which is the database's. Returns the free
    share, or None when it cannot be read."""
    import shutil

    from app.services import admin_alert

    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    free_pct = usage.free / usage.total * 100.0 if usage.total else 100.0
    if free_pct < float(settings.DISK_ALERT_FREE_PCT):
        message = (
            f"{usage.free / 1e9:.1f} GB free of {usage.total / 1e9:.0f} GB ({free_pct:.0f}%). "
            "The database is on this disk and stops when it is full."
        )
        logger.warning("disk low: %s", message)
        admin_alert.send_in_background(
            title="Hive's disk is nearly full",
            message=message,
            request_id=f"hive-disk-low-{_now().date().isoformat()}",
        )
    return free_pct


def _refresh_pass() -> dict[str, Any]:
    db = SessionLocal()
    try:
        free_pct = warn_if_disk_low()
        return {
            "last_run_machines": refresh_all(db),
            **LAST_PASS,
            "disk_free_pct": round(free_pct, 1) if free_pct is not None else None,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_INSTANCE: PeriodicWorker | None = None
_INSTANCE_LOCK = threading.Lock()


def get_machine_stats_worker() -> PeriodicWorker:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = PeriodicWorker(
                    "machine-stats-worker",
                    _refresh_pass,
                    # Read per pass, not once at startup, so changing the
                    # setting takes effect without a restart.
                    lambda: max(60.0, float(settings.MACHINE_STATS_REFRESH_INTERVAL_MINUTES) * 60.0),
                    # Prime the cache on boot so the first dashboard load is warm.
                    run_at_start=True,
                )
    return _INSTANCE


__all__ = [
    "refresh_cache",
    "refresh_all",
    "get_fleet_stats",
    "get_machine_stats",
    "get_machine_stats_worker",
    "piece_total",
    "channel_crop_total",
]
