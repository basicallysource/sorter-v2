"""What the sync worker sent to each Hive, hour by hour, and what it never will.

Per Hive target, per hour, per kind of upload (the sync legs, with records,
predictions, training runs and sorting runs counted together as piece records):

- sent, sent_bytes: rows or files Hive accepted, and their bytes.
- dropped, dropped_bytes: what will never reach that Hive: old samples skipped
  to keep up, and files deleted on the machine before they were sent (their
  rows still go, without the file).
- waiting: the most that waited to be sent during the hour.
- budget_wait_s: how long the file uploads waited for the upload budget.

Counts collect in memory and are written every FLUSH_INTERVAL_S, so a busy
upload costs no extra write. Hours older than KEEP_DAYS are deleted.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

import db

KIND_TELEMETRY = "telemetry"
KIND_PIECE_RECORDS = "piece_records"
KIND_PIECE_IMAGES = "piece_images"
KIND_SAMPLES = "samples"
KIND_CHANNEL_CROPS = "channel_crops"
KIND_CONTROL_DATA = "control_data"
# Display order, with the sharing stream each belongs to.
KINDS: tuple[tuple[str, str, str], ...] = (
    (KIND_TELEMETRY, "Machine telemetry", "machine_telemetry"),
    (KIND_PIECE_RECORDS, "Piece records", "piece_records"),
    (KIND_PIECE_IMAGES, "Piece pictures", "piece_images"),
    (KIND_SAMPLES, "Full camera frames", "camera_frames"),
    (KIND_CHANNEL_CROPS, "Channel crops", "channel_crops"),
    (KIND_CONTROL_DATA, "Feeder logs", "feeder_logs"),
)
KIND_KEYS = tuple(key for key, _label, _stream in KINDS)
# Not a kind: the budget is per target.
_BUDGET = "_budget"

FLUSH_INTERVAL_S = 30.0
KEEP_DAYS = 30.0

_COUNTERS = ("sent", "sent_bytes", "dropped", "dropped_bytes")

_lock = threading.Lock()
# (target_id, hour, kind) -> {"sent": n, ..., "waiting": max, "budget_wait_s": s}
_pending: dict[tuple[str, int, str], dict[str, float]] = {}
_last_flush = time.monotonic()


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS upload_stats ("
        "target_id TEXT NOT NULL, "
        "hour INTEGER NOT NULL, "
        "kind TEXT NOT NULL, "
        "sent INTEGER NOT NULL DEFAULT 0, "
        "sent_bytes INTEGER NOT NULL DEFAULT 0, "
        "dropped INTEGER NOT NULL DEFAULT 0, "
        "dropped_bytes INTEGER NOT NULL DEFAULT 0, "
        "waiting INTEGER, "
        "budget_wait_s REAL NOT NULL DEFAULT 0, "
        "last_sent_at REAL, "
        "PRIMARY KEY (target_id, hour, kind)"
        ")"
    )


def _connection():
    return db.connect(_createTables)


def _hour(at: float) -> int:
    return int(at // 3600) * 3600


def _entry(target_id: str, kind: str, at: float) -> dict[str, float]:
    key = (target_id, _hour(at), kind)
    entry = _pending.get(key)
    if entry is None:
        entry = _pending[key] = {}
    return entry


def noteSent(target_id: str, kind: str, items: int, nbytes: int, at: float | None = None) -> None:
    at = time.time() if at is None else at
    with _lock:
        entry = _entry(target_id, kind, at)
        entry["sent"] = entry.get("sent", 0) + items
        entry["sent_bytes"] = entry.get("sent_bytes", 0) + nbytes
        entry["last_sent_at"] = at
    _maybeFlush()


def noteDropped(target_id: str, kind: str, items: int, nbytes: int = 0, at: float | None = None) -> None:
    at = time.time() if at is None else at
    with _lock:
        entry = _entry(target_id, kind, at)
        entry["dropped"] = entry.get("dropped", 0) + items
        entry["dropped_bytes"] = entry.get("dropped_bytes", 0) + nbytes
    _maybeFlush()


def noteWaiting(target_id: str, waiting: dict[str, int | None], at: float | None = None) -> None:
    at = time.time() if at is None else at
    with _lock:
        for kind, count in waiting.items():
            if count is None:
                continue
            entry = _entry(target_id, kind, at)
            entry["waiting"] = max(entry.get("waiting", 0), count)


def noteBudgetWait(target_id: str, seconds: float, at: float | None = None) -> None:
    if seconds <= 0:
        return
    at = time.time() if at is None else at
    with _lock:
        entry = _entry(target_id, _BUDGET, at)
        entry["budget_wait_s"] = entry.get("budget_wait_s", 0.0) + seconds


def _maybeFlush() -> None:
    if time.monotonic() - _last_flush >= FLUSH_INTERVAL_S:
        flush()


def flush() -> None:
    global _last_flush
    with _lock:
        pending = dict(_pending)
        _pending.clear()
        _last_flush = time.monotonic()
    if not pending:
        return
    rows = [
        (
            target_id, hour, kind,
            int(entry.get("sent", 0)), int(entry.get("sent_bytes", 0)),
            int(entry.get("dropped", 0)), int(entry.get("dropped_bytes", 0)),
            int(entry["waiting"]) if "waiting" in entry else None,
            float(entry.get("budget_wait_s", 0.0)),
            entry.get("last_sent_at"),
        )
        for (target_id, hour, kind), entry in pending.items()
    ]
    with _connection() as conn:
        conn.executemany(
            "INSERT INTO upload_stats (target_id, hour, kind, sent, sent_bytes, dropped, dropped_bytes, "
            "waiting, budget_wait_s, last_sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(target_id, hour, kind) DO UPDATE SET "
            "sent = sent + excluded.sent, sent_bytes = sent_bytes + excluded.sent_bytes, "
            "dropped = dropped + excluded.dropped, dropped_bytes = dropped_bytes + excluded.dropped_bytes, "
            "waiting = CASE WHEN excluded.waiting IS NULL THEN waiting WHEN waiting IS NULL "
            "THEN excluded.waiting ELSE MAX(waiting, excluded.waiting) END, "
            "budget_wait_s = budget_wait_s + excluded.budget_wait_s, "
            "last_sent_at = CASE WHEN excluded.last_sent_at IS NULL THEN last_sent_at WHEN last_sent_at IS NULL "
            "THEN excluded.last_sent_at ELSE MAX(last_sent_at, excluded.last_sent_at) END",
            rows,
        )
        conn.commit()


def series(target_id: str, hours: int, now: float | None = None) -> dict[str, Any]:
    """The last `hours` hours for one target, the current hour last: per kind
    the counters as lists lined up with `hour_starts`, the budget wait per
    hour, and when each kind was last sent."""
    flush()
    now = time.time() if now is None else now
    last = _hour(now)
    hour_starts = [last - 3600 * i for i in range(hours - 1, -1, -1)]
    index = {hour: i for i, hour in enumerate(hour_starts)}
    out: dict[str, dict[str, list[Any]]] = {
        kind: {name: [0] * hours for name in _COUNTERS} | {"waiting": [None] * hours} for kind in KIND_KEYS
    }
    budget = [0.0] * hours
    last_sent: dict[str, float | None] = {kind: None for kind in KIND_KEYS}
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM upload_stats WHERE target_id = ? AND hour >= ? ORDER BY hour",
            (target_id, hour_starts[0]),
        ).fetchall()
        sent_rows = conn.execute(
            "SELECT kind, MAX(last_sent_at) AS at FROM upload_stats WHERE target_id = ? GROUP BY kind",
            (target_id,),
        ).fetchall()
    for row in rows:
        i = index.get(int(row["hour"]))
        if i is None:
            continue
        if row["kind"] == _BUDGET:
            budget[i] = round(float(row["budget_wait_s"]), 1)
            continue
        kind = out.get(row["kind"])
        if kind is None:
            continue
        for name in _COUNTERS:
            kind[name][i] = int(row[name])
        kind["waiting"][i] = row["waiting"]
    for row in sent_rows:
        if row["kind"] in last_sent and row["at"]:
            last_sent[row["kind"]] = float(row["at"])
    return {"hour_starts": hour_starts, "series": out, "budget_wait_s": budget, "last_sent_at": last_sent}


def prune(now: float) -> int:
    flush()
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM upload_stats WHERE hour < ?", (_hour(now - KEEP_DAYS * 86400.0),))
        conn.commit()
        return int(cursor.rowcount or 0)


def forgetTarget(target_id: str) -> None:
    with _lock:
        for key in [key for key in _pending if key[0] == target_id]:
            del _pending[key]
    with _connection() as conn:
        conn.execute("DELETE FROM upload_stats WHERE target_id = ?", (target_id,))
        conn.commit()
