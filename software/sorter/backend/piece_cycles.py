"""Every piece's trip through the classification channel (C4), one row each.

C4 asks the feeder for a piece (classification_ready -> True), the piece lands
in the drop zone, C4 photographs it, waits until the piece ahead of it is ready
to ship (classified, chute aimed), turns to eject that one and stage this one,
and asks again. A row keeps when each of those happened, and what the feeder
looked like at the ask: how far C3's nearest pieces were from its edge, and how
much of the wait C2, C3 and the chute spent moving. That says, for any stretch
of sorting, where each piece's seconds went: C4's own work, or waiting for the
feeder, and why.

The classification channel's flow feeds a CycleRecorder from the control loop;
finished rows go to the database on the writer thread.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, fields
from typing import Any, Optional

import db

KEEP_DAYS = 60.0

# Where C3's nearest piece was when C4 asked, in degrees still to go to C3's
# exit edge. The bands are what the wait depends on: a piece at the edge drops
# in about a second, one still in C3's landing area is most of a lap away.
WAIT_CASES = (
    ("edge", "C3's next piece within 20° of its edge", 0.0, 20.0),
    ("near", "20° to 80° from the edge", 20.0, 80.0),
    ("far", "more than 80° from the edge", 80.0, 1e9),
    ("empty", "no piece seen on C3", None, None),
)

_COLUMNS = {
    "asked_at": "REAL NOT NULL",
    "landed_at": "REAL",
    "confirmed_at": "REAL",
    "captured_at": "REAL",
    "rotated_at": "REAL",
    "ejected_at": "REAL",
    "staged_at": "REAL",
    "ejecting": "INTEGER",
    "c3_head_deg": "REAL",
    "c3_next_deg": "REAL",
    "c3_pieces": "INTEGER",
    "c2_pieces": "INTEGER",
    "c3_hidden": "INTEGER",
    "c3_moving_s": "REAL",
    "c2_moving_s": "REAL",
    "chute_s": "REAL",
    "track_id": "INTEGER",
    "piece_uuid": "TEXT",
    "multi_drop": "INTEGER",
    "note": "TEXT",
}


def _createTables(conn: sqlite3.Connection) -> None:
    cols = ", ".join(f"{name} {kind}" for name, kind in _COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS piece_cycles (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})")
    db.add_columns(conn, "piece_cycles", {k: v for k, v in _COLUMNS.items() if "NOT NULL" not in v})
    conn.execute("CREATE INDEX IF NOT EXISTS idx_piece_cycles_asked ON piece_cycles(asked_at)")
    conn.execute("DELETE FROM piece_cycles WHERE asked_at < ?", (time.time() - KEEP_DAYS * 86400.0,))


def _connection():
    return db.connect(_createTables)


@dataclass
class Cycle:
    asked_at: float
    landed_at: Optional[float] = None
    confirmed_at: Optional[float] = None
    captured_at: Optional[float] = None
    rotated_at: Optional[float] = None
    ejected_at: Optional[float] = None
    staged_at: Optional[float] = None
    ejecting: Optional[int] = None
    c3_head_deg: Optional[float] = None
    c3_next_deg: Optional[float] = None
    c3_pieces: Optional[int] = None
    c2_pieces: Optional[int] = None
    c3_hidden: Optional[int] = None
    c3_moving_s: float = 0.0
    c2_moving_s: float = 0.0
    chute_s: float = 0.0
    track_id: Optional[int] = None
    piece_uuid: Optional[str] = None
    multi_drop: int = 0
    note: Optional[str] = None


def _write(cycle: Cycle) -> None:
    values = {f.name: getattr(cycle, f.name) for f in fields(cycle)}
    names = list(values)
    with _connection() as conn:
        conn.execute(
            f"INSERT INTO piece_cycles ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
            [values[n] for n in names],
        )
        conn.commit()


def _gaps(state: Any) -> list[float]:
    out = []
    for p in getattr(state, "pieces", ()) or ():
        gap = getattr(p, "com_forward_to_exit_deg", None)
        if gap is not None:
            out.append(float(gap))
    return sorted(out)


class CycleRecorder:
    """The classification channel's flow calls these as its cycle happens. One
    cycle is open at a time: from C4's ask to its next ask (the end of
    staging). A pause or a forced clear drops the open cycle unwritten, so a
    stop never reads as a slow piece."""

    def __init__(self) -> None:
        self._open: Optional[Cycle] = None
        self._last_tick: Optional[float] = None

    @property
    def waiting(self) -> bool:
        return self._open is not None and self._open.landed_at is None

    def asked(self, now: float, c3_state: Any, c2_state: Any, c3_hidden: int = 0) -> None:
        cycle = self._open
        if cycle is not None and cycle.confirmed_at is None:
            # Something showed in the drop zone and left before it could be
            # photographed (a detector flicker, a piece sliding on): the same
            # wait goes on.
            cycle.landed_at = None
            return
        gaps = _gaps(c3_state)
        self._open = Cycle(
            asked_at=now,
            c3_head_deg=gaps[0] if gaps else None,
            c3_next_deg=gaps[1] if len(gaps) > 1 else None,
            c3_pieces=len(gaps),
            c2_pieces=len(_gaps(c2_state)),
            c3_hidden=int(c3_hidden),
        )
        self._last_tick = now

    def tick(self, now: float, *, c3_moving: bool, c2_moving: bool, chute_moving: bool) -> None:
        """While C4 waits, add up how long C3, C2 and the chute were moving."""
        cycle = self._open
        last = self._last_tick
        self._last_tick = now
        if cycle is None or cycle.landed_at is not None or last is None:
            return
        dt = max(0.0, min(now - last, 0.5))
        if c3_moving:
            cycle.c3_moving_s += dt
        if c2_moving:
            cycle.c2_moving_s += dt
        if chute_moving:
            cycle.chute_s += dt

    def landed(self, now: float) -> None:
        if self._open is not None and self._open.landed_at is None:
            self._open.landed_at = now

    def confirmed(self, now: float, track_id: int, piece_uuid: Optional[str]) -> None:
        cycle = self._open
        if cycle is not None and cycle.confirmed_at is None and cycle.landed_at is not None:
            cycle.confirmed_at = now
            cycle.track_id = int(track_id)
            cycle.piece_uuid = piece_uuid

    def captured(self, now: float, track_id: int) -> None:
        cycle = self._open
        if cycle is not None and cycle.captured_at is None and cycle.track_id == int(track_id):
            cycle.captured_at = now

    def multiDrop(self) -> None:
        if self._open is not None and self._open.landed_at is not None:
            self._open.multi_drop = 1

    def rotated(self, now: float, ejecting: bool) -> None:
        cycle = self._open
        if cycle is not None and cycle.rotated_at is None and cycle.landed_at is not None:
            cycle.rotated_at = now
            cycle.ejecting = int(bool(ejecting))

    def ejected(self, now: float) -> None:
        cycle = self._open
        if cycle is not None and cycle.rotated_at is not None and cycle.ejected_at is None:
            cycle.ejected_at = now

    def staged(self, now: float, note: Optional[str] = None) -> None:
        """The drop zone is clear again: the cycle ends and is written."""
        cycle = self._open
        self._open = None
        if cycle is None or cycle.landed_at is None:
            return
        cycle.staged_at = now
        cycle.note = note
        db.defer("piece_cycles.write", lambda: _write(cycle))

    def drop(self) -> None:
        self._open = None
        self._last_tick = None


# ------------------------------------------------------------------ reading


def _quantiles(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    v = sorted(values)
    n = len(v)
    return {
        "n": n,
        "median": v[n // 2],
        "mean": sum(v) / n,
        "p90": v[min(n - 1, int(n * 0.9))],
        "total": sum(v),
    }


def _case(head_deg: Optional[float]) -> str:
    if head_deg is None:
        return "empty"
    deg = max(0.0, head_deg)
    for key, _, lo, hi in WAIT_CASES:
        if lo is not None and hi is not None and lo <= deg < hi:
            return key
    return "far"


def listCycles(since: float, until: Optional[float] = None) -> list[dict[str, Any]]:
    until = time.time() if until is None else until
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM piece_cycles WHERE asked_at >= ? AND asked_at < ? ORDER BY asked_at",
            (since, until),
        ).fetchall()
    return [dict(r) for r in rows]


def _incidentSpans(since: float, until: float) -> list[tuple[float, float]]:
    try:
        import incident_records  # noqa: F401  (creates the table)

        with db.connect(incident_records._createTables) as conn:
            rows = conn.execute(
                "SELECT triggered_at, COALESCE(resolved_at, ?) FROM incidents "
                "WHERE triggered_at < ? AND COALESCE(resolved_at, ?) > ?",
                (until, until, until, since),
            ).fetchall()
        return [(float(a), float(b)) for a, b in rows]
    except Exception:
        return []


def summary(since: float, until: Optional[float] = None) -> dict[str, Any]:
    """Where the seconds went for every piece C4 took between since and until.
    Cycles that overlap an incident are left out and counted apart: they are
    stops, not the normal flow."""
    until = time.time() if until is None else until
    rows = listCycles(since, until)
    spans = _incidentSpans(since, until)

    def held(r: dict[str, Any]) -> bool:
        a, b = r["asked_at"], r["staged_at"] or r["asked_at"]
        return any(lo < b and hi > a for lo, hi in spans)

    normal = [r for r in rows if not held(r)]

    def span(a: str, b: str) -> list[float]:
        return [r[b] - r[a] for r in normal if r.get(a) is not None and r.get(b) is not None and r[b] >= r[a]]

    waits = span("asked_at", "landed_at")
    c4 = span("landed_at", "staged_at")
    cycle_s = [w + c for w, c in zip(waits, c4)] if len(waits) == len(c4) else []
    total_s = sum(r["staged_at"] - r["asked_at"] for r in normal if r.get("staged_at"))
    cases = []
    for key, label, _, _ in WAIT_CASES:
        sel = [r for r in normal if r.get("landed_at") is not None and _case(r.get("c3_head_deg")) == key]
        w = [r["landed_at"] - r["asked_at"] for r in sel]
        stats = _quantiles(w)
        stats.update(
            key=key,
            label=label,
            share=(len(sel) / len(normal)) if normal else 0.0,
            c3_moving=(sum(r["c3_moving_s"] or 0.0 for r in sel) / sum(w)) if w and sum(w) > 0 else None,
            chute=(sum(r["chute_s"] or 0.0 for r in sel) / sum(w)) if w and sum(w) > 0 else None,
        )
        cases.append(stats)
    long_waits = [w for w in waits if w > 4.0]
    return {
        "since": since,
        "until": until,
        "pieces": len(normal),
        "held": len(rows) - len(normal),
        "per_minute": (60.0 * len(normal) / total_s) if total_s > 0 else None,
        "multi_drop": sum(1 for r in normal if r.get("multi_drop")),
        "c4": {
            "confirm": _quantiles(span("landed_at", "confirmed_at")),
            "photos": _quantiles(span("confirmed_at", "captured_at")),
            "head_ready": _quantiles(span("captured_at", "rotated_at")),
            "turn": _quantiles(span("rotated_at", "staged_at")),
            "total": _quantiles(c4),
        },
        "wait": _quantiles(waits),
        "cycle": _quantiles(cycle_s),
        "wait_cases": cases,
        "long_waits": {"n": len(long_waits), "seconds": sum(long_waits), "share": (sum(long_waits) / sum(waits)) if waits else 0.0},
    }
