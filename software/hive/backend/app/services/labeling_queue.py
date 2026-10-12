"""The labeling queue: every piece a person can label, kept by a worker.

A piece is labelable when its record is not dead, at least one of its crops is
in storage, and it arrived over 15 minutes ago, so its upstream channel crops
have had time to sync. Finding those pieces at request time meant joining the
whole of machine_pieces to machine_piece_images and sorting the result, every
page (11 to 48 s at a million pieces). Instead this worker keeps one narrow row
per labelable piece in ``labeling_queue``, holding what the grid filters and
sorts on, and the grid walks an index on it and stops at the page size.

Every pass (``REFRESH_INTERVAL_S``):
  * pieces, and piece crops, that reached Hive since the last pass are
    evaluated: inserted, updated or removed. "Since the last pass" is by
    ``created_at`` with an overlap, so a row whose transaction was still open
    when the last pass read is not missed;
  * channel crops that reached Hive since the last pass mark the pieces whose
    arrival window they fall in as having same-piece candidates;
  * each machine's labelable count is recounted into ``labeling_queue_counts``.

Once a day (``RECONCILE_INTERVAL_S``) it evaluates every piece again, in small
batches, which catches what ``created_at`` cannot see: a record re-sent as
dead or re-classified, a crop whose file arrived on a later re-send. The first
pass after a deploy is such a full evaluation, and it is what fills the table.

Requests only read, through ``services.review_queue``. A piece that died since
it was last evaluated is dropped at read time by the join to machine_pieces, so
the queue never shows one.
"""

from __future__ import annotations

import bisect
import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.labeling_queue import LabelingQueueCount, LabelingQueueEntry, LabelingQueueState
from app.models.machine import Machine
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.services.channel_crop_lookup_params import DEFAULT_PARAMS
from app.services.periodic import PeriodicWorker

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_S = 300.0
RECONCILE_INTERVAL_S = 24 * 3600.0
# Re-read rows created this long before the last pass started: a sync request
# that was mid-transaction then commits rows stamped earlier than its commit.
OVERLAP = timedelta(minutes=10)
# A piece is shown once it arrived this long ago, so its channel crops (which
# upload after it) have had time to sync and the candidate list is complete.
MIN_PIECE_AGE = timedelta(minutes=15)
RECONCILE_BATCH = 5000
_IN_CHUNK = 500

# The same-piece window of the time/angle heuristic: a crop up to LOOKBACK
# seconds before the piece's arrival, or up to SLOP after it, may be the piece.
LOOKBACK_S = DEFAULT_PARAMS.lookback_window_s
SLOP_S = DEFAULT_PARAMS.fwd_slop_s

_PIECE_COLUMNS = (
    MachinePiece.machine_id,
    MachinePiece.piece_uuid,
    MachinePiece.local_id,
    MachinePiece.seen_at,
    MachinePiece.recorded_at,
    MachinePiece.created_at,
    MachinePiece.dead,
    MachinePiece.part_id,
    MachinePiece.color_id,
    MachinePiece.color_confidence,
)


def _utc(dt: datetime) -> datetime:
    # SQLite (the tests) hands datetimes back naive; every stored time is UTC.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _epoch(dt: datetime) -> float:
    return _utc(dt).timestamp()


def _arrival(piece: Any) -> datetime:
    return _utc(piece.seen_at or piece.recorded_at or piece.created_at)


def _insert_for(db: Session):
    return pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert


def _chunks(items: list, size: int = _IN_CHUNK) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# --- Evaluating pieces -----------------------------------------------------------


def _with_images(db: Session, machine_id: Any, piece_uuids: list[str]) -> set[str]:
    found: set[str] = set()
    for chunk in _chunks(piece_uuids):
        found.update(
            puid
            for (puid,) in db.query(MachinePieceImage.piece_uuid)
            .filter(
                MachinePieceImage.machine_id == machine_id,
                MachinePieceImage.piece_uuid.in_(chunk),
                MachinePieceImage.image_key.isnot(None),
            )
            .distinct()
        )
    return found


_RANGES_PER_READ = 100


def _with_candidates(db: Session, machine_id: Any, arrivals: dict[str, datetime]) -> set[str]:
    """Pieces with at least one channel crop in their arrival window.

    Pieces are grouped into runs whose windows touch (a sorting session is one
    run), and the crop timestamps of up to _RANGES_PER_READ runs are read in one
    query, each run an index-only range on (machine_id, ts). So a busy machine
    costs a range read per session and a quiet one, whose pieces are minutes
    apart, a query per hundred pieces rather than one each."""
    if not arrivals:
        return set()
    ordered = sorted(arrivals.items(), key=lambda kv: kv[1])
    runs: list[list[tuple[str, datetime]]] = [[ordered[0]]]
    for item in ordered[1:]:
        if (item[1] - runs[-1][-1][1]).total_seconds() > LOOKBACK_S + SLOP_S:
            runs.append([item])
        else:
            runs[-1].append(item)

    found: set[str] = set()
    for chunk in _chunks(runs, _RANGES_PER_READ):
        spans = [
            and_(
                MachineChannelCrop.ts >= run[0][1] - timedelta(seconds=LOOKBACK_S),
                MachineChannelCrop.ts <= run[-1][1] + timedelta(seconds=SLOP_S),
            )
            for run in chunk
        ]
        stamps = [
            _epoch(ts)
            for (ts,) in db.query(MachineChannelCrop.ts)
            .filter(MachineChannelCrop.machine_id == machine_id, or_(*spans))
            .order_by(MachineChannelCrop.ts)
        ]
        # Every crop in a piece's window lies in its run's span, so the
        # combined list answers each piece exactly.
        for run in chunk:
            for puid, arrival in run:
                a = _epoch(arrival)
                i = bisect.bisect_left(stamps, a - LOOKBACK_S)
                if i < len(stamps) and stamps[i] <= a + SLOP_S:
                    found.add(puid)
    return found


_QUEUE_FIELDS = ("arrival_at", "has_candidates", "unidentified", "color_id", "color_confidence")


def _comparable(row: Any) -> tuple:
    get = row.get if isinstance(row, dict) else lambda f: getattr(row, f)
    return (_utc(get("arrival_at")),) + tuple(get(f) for f in _QUEUE_FIELDS[1:])


def _queued(db: Session, machine_id: Any, piece_uuids: list[str]) -> dict[str, tuple]:
    current: dict[str, tuple] = {}
    for chunk in _chunks(piece_uuids):
        for entry in db.query(LabelingQueueEntry).filter(
            LabelingQueueEntry.machine_id == machine_id, LabelingQueueEntry.piece_uuid.in_(chunk)
        ):
            current[entry.piece_uuid] = _comparable(entry)
    return current


def evaluate(db: Session, pieces: list[Any]) -> dict[str, int]:
    """Bring the queue rows of these pieces up to date: insert or update the
    labelable ones, remove the rest. ``pieces`` are rows with _PIECE_COLUMNS.
    The caller commits."""
    by_machine: dict[Any, list[Any]] = defaultdict(list)
    for p in pieces:
        by_machine[p.machine_id].append(p)

    upserts: list[dict[str, Any]] = []
    removes: list[tuple[Any, str]] = []
    for machine_id, rows in by_machine.items():
        current = _queued(db, machine_id, [p.piece_uuid for p in rows])
        live = [p for p in rows if not p.dead]
        # What a queued row already knows is not asked again: a stored crop
        # never loses its key, and a crop in the arrival window never leaves it
        # (unless the arrival itself moved).
        with_image = {p.piece_uuid for p in live if p.piece_uuid in current}
        with_image |= _with_images(db, machine_id, [p.piece_uuid for p in live if p.piece_uuid not in current])
        eligible = [p for p in live if p.piece_uuid in with_image]
        known = {
            p.piece_uuid
            for p in eligible
            if p.piece_uuid in current and current[p.piece_uuid][1] and current[p.piece_uuid][0] == _arrival(p)
        }
        candidates = known | _with_candidates(
            db, machine_id, {p.piece_uuid: _arrival(p) for p in eligible if p.piece_uuid not in known}
        )
        eligible_ids = {p.piece_uuid for p in eligible}
        removes.extend(
            (machine_id, p.piece_uuid) for p in rows if p.piece_uuid not in eligible_ids and p.piece_uuid in current
        )
        for p in eligible:
            row = {
                "machine_id": p.machine_id,
                "piece_uuid": p.piece_uuid,
                "arrival_at": _arrival(p),
                "has_candidates": p.piece_uuid in candidates,
                "unidentified": not p.part_id,
                "color_id": p.color_id,
                "color_confidence": p.color_confidence,
            }
            # Only write what changed: the daily reconcile touches every piece,
            # and rewriting unchanged rows would double the table until vacuum.
            if current.get(p.piece_uuid) != _comparable(row):
                upserts.append(row)

    insert = _insert_for(db)
    for chunk in _chunks(upserts):
        stmt = insert(LabelingQueueEntry).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["machine_id", "piece_uuid"],
            set_={col: getattr(stmt.excluded, col) for col in _QUEUE_FIELDS},
        )
        db.execute(stmt)
    removed_by_machine: dict[Any, list[str]] = defaultdict(list)
    for machine_id, puid in removes:
        removed_by_machine[machine_id].append(puid)
    for machine_id, puids in removed_by_machine.items():
        for chunk in _chunks(puids):
            db.query(LabelingQueueEntry).filter(
                LabelingQueueEntry.machine_id == machine_id,
                LabelingQueueEntry.piece_uuid.in_(chunk),
            ).delete(synchronize_session=False)
    return {"queued": len(upserts), "removed": len(removes)}


def _pieces_by_keys(db: Session, keys: set[tuple[Any, str]]) -> list[Any]:
    by_machine: dict[Any, list[str]] = defaultdict(list)
    for machine_id, puid in keys:
        by_machine[machine_id].append(puid)
    rows: list[Any] = []
    for machine_id, puids in by_machine.items():
        for chunk in _chunks(puids):
            rows.extend(
                db.query(*_PIECE_COLUMNS).filter(
                    MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid.in_(chunk)
                )
            )
    return rows


def _changed_pieces(db: Session, since: datetime) -> list[Any]:
    """Pieces that reached Hive since ``since``, plus the pieces of piece crops
    that did. machine_pieces is read through its (machine_id, created_at) index
    one machine at a time; the two crop tables through BRIN indexes on
    created_at (they only ever append)."""
    machine_ids = [mid for (mid,) in db.query(Machine.id)]
    keys: set[tuple[Any, str]] = set()
    if machine_ids:
        keys.update(
            (mid, puid)
            for mid, puid in db.query(MachinePiece.machine_id, MachinePiece.piece_uuid).filter(
                MachinePiece.machine_id.in_(machine_ids), MachinePiece.created_at >= since
            )
        )
    keys.update(
        (mid, puid)
        for mid, puid in db.query(MachinePieceImage.machine_id, MachinePieceImage.piece_uuid)
        .filter(MachinePieceImage.created_at >= since, MachinePieceImage.image_key.isnot(None))
        .distinct()
    )
    return _pieces_by_keys(db, keys)


def _mark_candidates(db: Session, since: datetime) -> int:
    """Channel crops that reached Hive since ``since`` give the queued pieces
    whose arrival window holds them a candidate. A crop at ts belongs to pieces
    that arrived in [ts - SLOP, ts + LOOKBACK]; overlapping ranges are merged
    per machine, so a busy machine costs a few range updates."""
    ranges: dict[Any, list[tuple[datetime, datetime]]] = defaultdict(list)
    for machine_id, ts in (
        db.query(MachineChannelCrop.machine_id, MachineChannelCrop.ts)
        .filter(MachineChannelCrop.created_at >= since, MachineChannelCrop.ts.isnot(None))
        .order_by(MachineChannelCrop.machine_id, MachineChannelCrop.ts)
    ):
        ts = _utc(ts)
        lo, hi = ts - timedelta(seconds=SLOP_S), ts + timedelta(seconds=LOOKBACK_S)
        spans = ranges[machine_id]
        if spans and lo <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
        else:
            spans.append((lo, hi))
    marked = 0
    for machine_id, spans in ranges.items():
        for lo, hi in spans:
            marked += (
                db.query(LabelingQueueEntry)
                .filter(
                    LabelingQueueEntry.machine_id == machine_id,
                    LabelingQueueEntry.arrival_at >= lo,
                    LabelingQueueEntry.arrival_at <= hi,
                    LabelingQueueEntry.has_candidates.is_(False),
                )
                .update({LabelingQueueEntry.has_candidates: True}, synchronize_session=False)
            )
    return marked


def _recount(db: Session, now: datetime) -> None:
    counts = dict(
        db.query(LabelingQueueEntry.machine_id, func.count())
        .filter(LabelingQueueEntry.arrival_at <= now - MIN_PIECE_AGE)
        .group_by(LabelingQueueEntry.machine_id)
        .all()
    )
    db.query(LabelingQueueCount).delete(synchronize_session=False)
    for machine_id, n in counts.items():
        db.add(LabelingQueueCount(machine_id=machine_id, labelable=int(n), computed_at=now))


def reconcile(db: Session) -> int:
    """Evaluate every piece, one machine and one batch of local ids at a time,
    each batch its own short transaction. Returns pieces evaluated."""
    total = 0
    for (machine_id,) in db.query(Machine.id).all():
        after: tuple[int, str] | None = None
        while True:
            q = db.query(*_PIECE_COLUMNS).filter(MachinePiece.machine_id == machine_id)
            if after is not None:
                q = q.filter(tuple_(MachinePiece.local_id, MachinePiece.piece_uuid) > after)
            batch = q.order_by(MachinePiece.local_id, MachinePiece.piece_uuid).limit(RECONCILE_BATCH).all()
            if not batch:
                break
            evaluate(db, batch)
            db.commit()
            total += len(batch)
            after = (batch[-1].local_id, batch[-1].piece_uuid)
    # Rows whose piece is gone. The foreign key cascades on Postgres; this is for
    # a database that does not enforce it.
    orphans = (
        select(LabelingQueueEntry.machine_id, LabelingQueueEntry.piece_uuid)
        .outerjoin(
            MachinePiece,
            and_(
                MachinePiece.machine_id == LabelingQueueEntry.machine_id,
                MachinePiece.piece_uuid == LabelingQueueEntry.piece_uuid,
            ),
        )
        .where(MachinePiece.id.is_(None))
    )
    for machine_id, puid in db.execute(orphans).all():
        db.query(LabelingQueueEntry).filter(
            LabelingQueueEntry.machine_id == machine_id, LabelingQueueEntry.piece_uuid == puid
        ).delete(synchronize_session=False)
    db.commit()
    return total


def run_pass(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """One worker pass on a session: full reconcile when due, else the rows
    that arrived since the last pass; then the per-machine counts."""
    started = now or datetime.now(timezone.utc)
    state = db.get(LabelingQueueState, 1)
    if state is None:
        state = LabelingQueueState(id=1)
        db.add(state)
        db.flush()

    detail: dict[str, Any]
    reconciled_at = _utc(state.reconciled_at) if state.reconciled_at else None
    if reconciled_at is None or (started - reconciled_at).total_seconds() >= RECONCILE_INTERVAL_S:
        detail = {"mode": "reconcile", "evaluated": reconcile(db)}
        state = db.get(LabelingQueueState, 1)
        state.reconciled_at = started
    else:
        last = _utc(state.last_pass_at) if state.last_pass_at else reconciled_at
        since = last - OVERLAP
        pieces = _changed_pieces(db, since)
        result = evaluate(db, pieces)
        detail = {"mode": "incremental", "evaluated": len(pieces), **result, "marked": _mark_candidates(db, since)}
    state.last_pass_at = started
    _recount(db, datetime.now(timezone.utc))
    db.commit()
    return detail


def _pass() -> dict[str, Any]:
    db = SessionLocal()
    try:
        return run_pass(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_worker: PeriodicWorker | None = None
_worker_lock = threading.Lock()


def get_labeling_queue_worker() -> PeriodicWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = PeriodicWorker(
                "labeling-queue-worker",
                _pass,
                lambda: REFRESH_INTERVAL_S,
                # The first pass after a deploy fills the table when it is new.
                run_at_start=True,
            )
        return _worker
