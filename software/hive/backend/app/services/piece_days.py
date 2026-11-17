"""Per machine-day partial answers over machine_pieces, kept current a day at a time.

The stats worker used to answer every piece question (counts, distinct parts and
colours, active time, the daily table, the fleet's mass and records) with
grouped scans over the whole of machine_pieces, every pass. At two million
pieces those scans ran past the worker's 60 s statement limit and the stats
froze. This module keeps the partial answers instead (``models/machine_piece_day``)
and recomputes only the machine-days that changed:

* Triggers on machine_pieces append a mark (machine, UTC day of ``seen_at``)
  for every insert, delete and update of a column the stats read, old day and
  new.
* ``refresh_machine`` takes a machine's marks, recomputes each marked day from
  its pieces (an index range on (machine_id, seen_at)), then recomputes the
  machine's per-key totals for only the keys those days held before or hold
  now, and folds the machine's day rows (a few hundred at most) into its
  totals and its rows of the daily table.

The numbers are the old scans' numbers, computed differently: every count is a
sum over days, a distinct count is the number of keys, a name is the max over
days (in the database, so its collation decides as before), and active time is
the sum of each day's gaps plus the gap across each midnight, from the day
rows' first and last pieces. ``tests/test_piece_days.py`` checks it against the
full scan.

A machine whose pieces predate the triggers is counted in full once
(``seed``): every day it has is marked, and the next refresh builds them.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import Date, and_, cast, delete, func, insert, literal, literal_column, select, text, update
from sqlalchemy.orm import Session

from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_day import (
    KIND_COLOR,
    KIND_COMBO,
    KIND_PART,
    KIND_STATUS,
    NULL_DAY,
    MachinePieceDay,
    MachinePieceDayKey,
    MachinePieceDayMark,
    MachinePieceKey,
)

logger = logging.getLogger(__name__)

# Two pieces more than this many seconds apart are separate sorting sessions:
# the gap between them is not active time. machine_stats re-exports it.
ACTIVE_GAP_IDLE_S = 60.0
_IDLE = Decimal(str(ACTIVE_GAP_IDLE_S))

# Values that are not a part or a colour: the bucket a profile sorts into when
# it does not care. The fleet's newest finds leave them out.
NOT_A_KEY = ("", "any_color")
COMBO_SEP = "\t"

_IN_CHUNK = 500
_MICRO = Decimal(1_000_000)


def _postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _utc(dt: datetime | None) -> datetime | None:
    # sqlite (the tests) hands datetimes back naive; every stored time is UTC.
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _seconds(delta: timedelta) -> Decimal:
    """A gap in exact seconds, as Postgres's EXTRACT(EPOCH FROM interval) gives it."""
    return Decimal(delta // timedelta(microseconds=1)) / _MICRO


def _chunks(items: list, size: int = _IN_CHUNK) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def lock_machine(db: Session, machine_id: Any) -> None:
    """Hold this machine's stats for the rest of the transaction, so a request
    computing a new machine and the worker never rebuild one machine at once."""
    if _postgres(db):
        key = int.from_bytes(machine_id.bytes[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


# --- Seeding ------------------------------------------------------------------------


def seed(db: Session, machine_id: Any) -> int:
    """Mark every day this machine has pieces on, so the next refresh builds
    them all. For a machine whose pieces predate the triggers. The caller
    commits. Returns the days marked."""
    if _postgres(db):
        day = func.coalesce(cast(func.timezone("UTC", MachinePiece.seen_at), Date), literal(NULL_DAY, Date))
    else:
        day = func.coalesce(func.date(MachinePiece.seen_at), NULL_DAY.isoformat())
    # Days, read off the (machine_id, seen_at) index; then one mark per day.
    days = [
        d if isinstance(d, date) else date.fromisoformat(d)
        for (d,) in db.execute(select(day).where(MachinePiece.machine_id == machine_id).distinct())
    ]
    for chunk in _chunks(days):
        db.execute(insert(MachinePieceDayMark), [{"machine_id": machine_id, "day": d} for d in chunk])
    return len(days)


# --- Rebuilding one day ---------------------------------------------------------------


def _day_filter(machine_id: Any, day: date):
    if day == NULL_DAY:
        return and_(MachinePiece.machine_id == machine_id, MachinePiece.seen_at.is_(None))
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return and_(
        MachinePiece.machine_id == machine_id,
        MachinePiece.seen_at >= start,
        MachinePiece.seen_at < start + timedelta(days=1),
    )


def _active_within(db: Session, machine_id: Any, day: date) -> Decimal:
    """Gaps of up to ACTIVE_GAP_IDLE_S between consecutive pieces of the day."""
    if day == NULL_DAY:
        return Decimal(0)
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    if _postgres(db):
        value = db.execute(
            text(
                """
                SELECT COALESCE(SUM(CASE WHEN gap > 0 AND gap <= :idle THEN gap ELSE 0 END), 0)
                FROM (
                    SELECT EXTRACT(EPOCH FROM (seen_at - LAG(seen_at) OVER (ORDER BY seen_at, local_id))) AS gap
                    FROM machine_pieces
                    WHERE machine_id = :m AND seen_at >= :start AND seen_at < :end
                ) g
                """
            ),
            {"idle": ACTIVE_GAP_IDLE_S, "m": machine_id, "start": start, "end": start + timedelta(days=1)},
        ).scalar()
        return Decimal(value or 0)
    total = Decimal(0)
    prev = None
    for (seen_at,) in db.execute(
        select(MachinePiece.seen_at)
        .where(_day_filter(machine_id, day))
        .order_by(MachinePiece.seen_at, MachinePiece.local_id)
    ):
        seen_at = _utc(seen_at)
        if prev is not None:
            gap = _seconds(seen_at - prev)
            if 0 < gap <= _IDLE:
                total += gap
        prev = seen_at
    return total


def _key_selects(machine_id: Any, day: date) -> list:
    """The day's key rows, as SELECTs in MachinePieceDayKey's column order."""
    where = _day_filter(machine_id, day)
    day_value = literal(day, MachinePieceDayKey.day.type)
    classified = MachinePiece.classification_status == "classified"
    first_classified = func.min(MachinePiece.seen_at).filter(classified)
    status = func.coalesce(MachinePiece.classification_status, literal_column("'unknown'"))
    selects = [
        select(
            MachinePiece.machine_id, literal(KIND_STATUS), status, day_value,
            func.count(), literal(None, MachinePieceDayKey.name.type), first_classified,
        ).where(where).group_by(MachinePiece.machine_id, status),
    ]
    for kind, column, name in (
        (KIND_PART, MachinePiece.part_id, MachinePiece.part_name),
        (KIND_COLOR, MachinePiece.color_id, MachinePiece.color_name),
    ):
        selects.append(
            select(
                MachinePiece.machine_id, literal(kind), column, day_value,
                func.count(), func.max(name), first_classified,
            ).where(where, column.isnot(None)).group_by(MachinePiece.machine_id, column)
        )
    if day != NULL_DAY:
        # A classified part in a colour, only for the fleet's newest finds:
        # the pieces those count (both set, both real) and nothing else.
        combo = MachinePiece.part_id + COMBO_SEP + MachinePiece.color_id
        selects.append(
            select(
                MachinePiece.machine_id, literal(KIND_COMBO), combo, day_value,
                func.count(), literal(None, MachinePieceDayKey.name.type), func.min(MachinePiece.seen_at),
            )
            .where(
                where,
                classified,
                MachinePiece.part_id.isnot(None),
                MachinePiece.part_id.notin_(NOT_A_KEY),
                MachinePiece.color_id.isnot(None),
                MachinePiece.color_id.notin_(NOT_A_KEY),
            )
            .group_by(MachinePiece.machine_id, MachinePiece.part_id, MachinePiece.color_id)
        )
    return selects


_DAY_KEY_COLUMNS = ["machine_id", "kind", "key", "day", "n", "name", "first_classified"]


def _day_keys(db: Session, machine_id: Any, day: date) -> set[tuple[str, str]]:
    return {
        (kind, key)
        for kind, key in db.execute(
            select(MachinePieceDayKey.kind, MachinePieceDayKey.key).where(
                MachinePieceDayKey.machine_id == machine_id, MachinePieceDayKey.day == day
            )
        )
    }


def rebuild_day(db: Session, machine_id: Any, day: date) -> set[tuple[str, str]]:
    """Recompute one machine-day from its pieces. Returns the (kind, key) pairs
    it held before or holds now: the machine totals that may have changed."""
    touched = _day_keys(db, machine_id, day)
    db.execute(
        delete(MachinePieceDayKey).where(MachinePieceDayKey.machine_id == machine_id, MachinePieceDayKey.day == day)
    )
    db.execute(delete(MachinePieceDay).where(MachinePieceDay.machine_id == machine_id, MachinePieceDay.day == day))

    totals = db.execute(
        select(
            func.count(),
            func.count(MachinePiece.bin_x),
            func.count().filter(MachinePiece.classification_status == "classified"),
            func.min(MachinePiece.seen_at),
            func.max(MachinePiece.seen_at),
        ).where(_day_filter(machine_id, day))
    ).one()
    if not totals[0]:
        return touched
    # Core statements throughout, not the ORM: these rows are deleted and
    # written again by statement, and a session's identity map would hold
    # stale copies of them across passes.
    db.execute(
        insert(MachinePieceDay).values(
            machine_id=machine_id,
            day=day,
            pieces=int(totals[0]),
            distributed=int(totals[1]),
            classified=int(totals[2]),
            first_seen=totals[3],
            last_seen=totals[4],
            active_within=_active_within(db, machine_id, day),
            computed_at=datetime.now(timezone.utc),
        )
    )
    for query in _key_selects(machine_id, day):
        db.execute(insert(MachinePieceDayKey).from_select(_DAY_KEY_COLUMNS, query))
    return touched | _day_keys(db, machine_id, day)


def rebuild_machine_keys(db: Session, machine_id: Any, touched: set[tuple[str, str]]) -> None:
    """Recompute the machine's totals for these keys from its day rows."""
    by_kind: dict[str, list[str]] = defaultdict(list)
    for kind, key in touched:
        by_kind[kind].append(key)
    for kind, keys in by_kind.items():
        for chunk in _chunks(sorted(keys)):
            db.execute(
                delete(MachinePieceKey).where(
                    MachinePieceKey.machine_id == machine_id,
                    MachinePieceKey.kind == kind,
                    MachinePieceKey.key.in_(chunk),
                )
            )
            db.execute(
                insert(MachinePieceKey).from_select(
                    ["machine_id", "kind", "key", "n", "name", "first_classified"],
                    select(
                        MachinePieceDayKey.machine_id,
                        MachinePieceDayKey.kind,
                        MachinePieceDayKey.key,
                        func.sum(MachinePieceDayKey.n),
                        func.max(MachinePieceDayKey.name),
                        func.min(MachinePieceDayKey.first_classified),
                    )
                    .where(
                        MachinePieceDayKey.machine_id == machine_id,
                        MachinePieceDayKey.kind == kind,
                        MachinePieceDayKey.key.in_(chunk),
                    )
                    .group_by(MachinePieceDayKey.machine_id, MachinePieceDayKey.kind, MachinePieceDayKey.key),
                )
            )


# --- Folding a machine -------------------------------------------------------------------


@dataclass
class MachinePieces:
    """One machine's piece numbers, in the shape machine_stats caches."""

    pieces_seen: int = 0
    distributed: int = 0
    classified: int = 0
    unique_parts: int = 0
    unique_colors: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    active_seconds: float = 0.0
    distributions: dict[str, Any] = field(default_factory=lambda: {"status": {}, "parts": {}, "colors": {}})
    # (day, pieces, distributed, active seconds) for the daily table: days with
    # a seen_at, each day's active time including the gap across its midnight.
    daily: list[tuple[date, int, int, float]] = field(default_factory=list)

    def as_stats(self) -> dict[str, Any]:
        active = self.active_seconds
        span = (self.last_seen - self.first_seen).total_seconds() if self.first_seen and self.last_seen else 0.0
        return {
            "pieces_seen": self.pieces_seen,
            "distributed": self.distributed,
            "classified": self.classified,
            "unique_parts": self.unique_parts,
            "unique_colors": self.unique_colors,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "active_seconds": active,
            "overall_ppm": (self.distributed * 60.0 / active) if active > 0 else 0.0,
            "ontime_pct": (active / span * 100.0) if span > 0 else 0.0,
        }


def fold(db: Session, machine_id: Any) -> MachinePieces:
    """The machine's numbers from its day rows and key totals."""
    out = MachinePieces()
    active = Decimal(0)
    prev_last: datetime | None = None
    for row in db.execute(
        select(
            MachinePieceDay.day,
            MachinePieceDay.pieces,
            MachinePieceDay.distributed,
            MachinePieceDay.classified,
            MachinePieceDay.first_seen,
            MachinePieceDay.last_seen,
            MachinePieceDay.active_within,
        )
        .where(MachinePieceDay.machine_id == machine_id)
        .order_by(MachinePieceDay.day)
    ):
        out.pieces_seen += row.pieces
        out.distributed += row.distributed
        out.classified += row.classified
        if row.day == NULL_DAY:
            continue
        first, last = _utc(row.first_seen), _utc(row.last_seen)
        # A float only on sqlite: through its shortest repr, not its binary value.
        day_active = row.active_within if isinstance(row.active_within, Decimal) else Decimal(str(row.active_within))
        if prev_last is not None:
            gap = _seconds(first - prev_last)
            if 0 < gap <= _IDLE:
                day_active += gap
        active += day_active
        out.daily.append((row.day, row.pieces, row.distributed, float(day_active)))
        out.first_seen = first if out.first_seen is None else min(out.first_seen, first)
        out.last_seen = last if out.last_seen is None else max(out.last_seen, last)
        prev_last = last
    out.active_seconds = float(active)

    dist = out.distributions
    for kind, key, n, name in db.execute(
        select(MachinePieceKey.kind, MachinePieceKey.key, MachinePieceKey.n, MachinePieceKey.name).where(
            MachinePieceKey.machine_id == machine_id,
            MachinePieceKey.kind.in_((KIND_STATUS, KIND_PART, KIND_COLOR)),
        )
    ):
        if kind == KIND_STATUS:
            dist["status"][key] = int(n)
        elif kind == KIND_PART:
            dist["parts"][key] = [int(n), name]
        else:
            dist["colors"][key] = [int(n), name]
    out.unique_parts = len(dist["parts"])
    out.unique_colors = len(dist["colors"])
    return out


def write_daily(db: Session, machine_id: Any, daily: list[tuple[date, int, int, float]]) -> None:
    """Bring the machine's machine_daily_stats rows to these, writing only what changed."""
    t = MachineDailyStats
    existing = {
        day: (pieces, distributed, active)
        for day, pieces, distributed, active in db.execute(
            select(t.day, t.pieces_seen, t.distributed, t.active_seconds).where(t.machine_id == machine_id)
        )
    }
    for day, pieces, distributed, active in daily:
        values = {"pieces_seen": pieces, "distributed": distributed, "active_seconds": active}
        before = existing.pop(day, None)
        if before is None:
            db.execute(insert(t).values(machine_id=machine_id, day=day, **values))
        elif before != (pieces, distributed, active):
            db.execute(update(t).where(t.machine_id == machine_id, t.day == day).values(**values))
    for chunk in _chunks(sorted(existing)):
        db.execute(delete(t).where(t.machine_id == machine_id, t.day.in_(chunk)))


# --- The pass -----------------------------------------------------------------------------


def take_marks(db: Session, machine_id: Any) -> set[date]:
    """Remove and return the machine's marked days. A mark a write commits
    after this stays for the next pass."""
    return {
        d
        for (d,) in db.execute(
            delete(MachinePieceDayMark).where(MachinePieceDayMark.machine_id == machine_id).returning(MachinePieceDayMark.day)
        )
    }


def marked_machines(db: Session) -> set[Any]:
    return {mid for (mid,) in db.execute(select(MachinePieceDayMark.machine_id).distinct())}


def refresh_machine(db: Session, machine_id: Any) -> tuple[MachinePieces, int] | None:
    """Rebuild the machine's marked days and its totals. Returns its numbers and
    how many days were rebuilt, or None when nothing was marked. The caller
    holds the machine's lock and commits."""
    days = take_marks(db, machine_id)
    if not days:
        return None
    touched: set[tuple[str, str]] = set()
    for day in sorted(days):
        touched |= rebuild_day(db, machine_id, day)
    rebuild_machine_keys(db, machine_id, touched)
    folded = fold(db, machine_id)
    write_daily(db, machine_id, folded.daily)
    return folded, len(days)


def forget_gone_machines(db: Session, machine_ids: set[Any]) -> int:
    """Drop the marks of machines that no longer exist (a deleted machine's
    cascade marks its days on the way out)."""
    gone = marked_machines(db) - set(machine_ids)
    for chunk in _chunks(list(gone)):
        db.execute(delete(MachinePieceDayMark).where(MachinePieceDayMark.machine_id.in_(chunk)))
    return len(gone)
