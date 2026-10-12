"""Every prediction the machine made for a piece, kept and sent to Hive.

One row per ranked answer: each classification request's parts and colours
(Brickognize: the top PREDICTIONS_PER_REQUEST of each, with scores) and the
hosted colour model's top three. Written once, when the piece's
classification settles, applied or not; `applied` marks the one part and the
one colour the piece took. Rows never change, so they sync by id.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Iterable, Optional

import db

# Brickognize ranks per request kept for each kind (part, colour).
PREDICTIONS_PER_REQUEST = 5
# The hosted colour model answers with its top three.
HOSTED_COLORS = 3

KIND_PART = "part"
KIND_COLOR = "color"
REQUEST_HOSTED = "hosted"

# The latest pieces' predictions, so a piece still in the runtime lookup (whose
# detail the UI polls while sorting) is served without touching the database.
_RECENT_MAX = 2000
_recent_lock = threading.Lock()
_recent: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()

_COLUMNS = (
    "piece_uuid", "request", "provider", "model", "kind", "rank",
    "value_id", "value_name", "score", "applied", "created_at",
)


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS piece_predictions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "piece_uuid TEXT NOT NULL, "
        # Which request answered: a Brickognize request's label (combined,
        # single_burst) or "hosted" for the hosted colour model.
        "request TEXT NOT NULL, "
        "provider TEXT NOT NULL, "
        # The model's identity when the provider reports one (the hosted
        # model's sha256); NULL for Brickognize.
        "model TEXT, "
        "kind TEXT NOT NULL, "
        # 0-based, in the provider's own order.
        "rank INTEGER NOT NULL, "
        # A BrickLink colour id (as text) for a colour, a part number for a part.
        "value_id TEXT NOT NULL, "
        "value_name TEXT, "
        "score REAL, "
        "applied INTEGER NOT NULL DEFAULT 0, "
        "created_at REAL NOT NULL, "
        "UNIQUE(piece_uuid, request, kind, rank)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_piece_predictions_uuid ON piece_predictions(piece_uuid)"
    )


def _connection():
    return db.connect(_createTables)


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def fromClassification(
    *,
    attempts: Iterable[Any],
    hosted: Optional[dict[str, Any]],
    applied_part: Optional[tuple[str, Optional[int]]],
    applied_color: Optional[tuple[str, Optional[str], Optional[int]]],
    created_at: Optional[float] = None,
) -> list[dict[str, Any]]:
    """The rows for one piece, from its classification attempts (each with
    `label`, `applied`, `items` and `colors`: ranked dicts with id, name,
    score, rank) and the hosted colour model's answer (`top`: dicts with
    color_id, color_name, confidence; `model_sha256`).

    `applied_part` is (part id, Brickognize rank) of the part the piece took;
    `applied_color` is (provider, colour id, Brickognize rank) of its colour."""
    now = float(created_at) if created_at is not None else time.time()
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        label = getattr(attempt, "label", None) or getattr(getattr(attempt, "strategy", None), "value", None)
        if not label:
            continue
        took_this_request = bool(getattr(attempt, "applied", False))
        for kind, entries in ((KIND_PART, getattr(attempt, "items", None)), (KIND_COLOR, getattr(attempt, "colors", None))):
            for position, entry in enumerate(entries or []):
                if not isinstance(entry, dict) or entry.get("id") is None:
                    continue
                rank = entry.get("rank")
                rank = int(rank) if isinstance(rank, int) else position
                value_id = str(entry["id"])
                if kind == KIND_PART:
                    applied = (
                        took_this_request
                        and applied_part is not None
                        and applied_part[0] == value_id
                        and applied_part[1] == rank
                    )
                else:
                    applied = (
                        took_this_request
                        and applied_color is not None
                        and applied_color[0] == "brickognize"
                        and applied_color[1] == value_id
                        and applied_color[2] == rank
                    )
                rows.append({
                    "request": str(label),
                    "provider": "brickognize",
                    "model": None,
                    "kind": kind,
                    "rank": rank,
                    "value_id": value_id,
                    "value_name": str(entry["name"]) if entry.get("name") is not None else None,
                    "score": _num(entry.get("score")),
                    "applied": applied,
                    "created_at": now,
                })
    if isinstance(hosted, dict):
        model = hosted.get("model_sha256")
        for rank, entry in enumerate((hosted.get("top") or [])[:HOSTED_COLORS]):
            if not isinstance(entry, dict) or entry.get("color_id") is None:
                continue
            value_id = str(entry["color_id"])
            rows.append({
                "request": REQUEST_HOSTED,
                "provider": "hive_basically",
                "model": str(model) if model else None,
                "kind": KIND_COLOR,
                "rank": rank,
                "value_id": value_id,
                "value_name": str(entry["color_name"]) if entry.get("color_name") is not None else None,
                "score": _num(entry.get("confidence")),
                "applied": (
                    rank == 0
                    and applied_color is not None
                    and applied_color[0] == "hive_basically"
                    and applied_color[1] == value_id
                ),
                "created_at": now,
            })
    return rows


def recordPredictions(piece_uuid: str, rows: list[dict[str, Any]]) -> None:
    """Store a piece's predictions. A piece classified again (a retry) adds
    nothing for a (request, kind, rank) it already has."""
    if not isinstance(piece_uuid, str) or not piece_uuid or not rows:
        return
    with _connection() as conn:
        conn.executemany(
            f"INSERT OR IGNORE INTO piece_predictions ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
            [
                (
                    piece_uuid,
                    r["request"],
                    r["provider"],
                    r.get("model"),
                    r["kind"],
                    int(r["rank"]),
                    r["value_id"],
                    r.get("value_name"),
                    r.get("score"),
                    1 if r.get("applied") else 0,
                    float(r.get("created_at") or time.time()),
                )
                for r in rows
            ],
        )
        conn.commit()


def _rowToPrediction(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "request": row["request"],
        "provider": row["provider"],
        "model": row["model"],
        "kind": row["kind"],
        "rank": int(row["rank"]),
        "value_id": row["value_id"],
        "value_name": row["value_name"],
        "score": row["score"],
        "applied": bool(row["applied"]),
    }


def listForPiece(piece_uuid: str) -> list[dict[str, Any]]:
    """A piece's predictions, ordered by kind, request and rank."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT request, provider, model, kind, rank, value_id, value_name, score, applied "
            "FROM piece_predictions WHERE piece_uuid = ? ORDER BY kind, request, rank",
            (piece_uuid,),
        ).fetchall()
    return [_rowToPrediction(r) for r in rows]


def remember(piece_uuid: str, rows: list[dict[str, Any]]) -> None:
    """Keep a just-classified piece's predictions in memory (see _recent)."""
    keys = ("request", "provider", "model", "kind", "rank", "value_id", "value_name", "score", "applied")
    shaped = sorted(
        ({key: r.get(key) for key in keys} for r in rows),
        key=lambda r: (r["kind"], r["request"], r["rank"]),
    )
    with _recent_lock:
        _recent[piece_uuid] = shaped
        _recent.move_to_end(piece_uuid)
        while len(_recent) > _RECENT_MAX:
            _recent.popitem(last=False)


def recent(piece_uuid: str) -> list[dict[str, Any]]:
    """A piece's predictions from memory, in listForPiece's shape and order;
    empty when this process did not classify it."""
    with _recent_lock:
        rows = _recent.get(piece_uuid)
    return [dict(r) for r in rows] if rows else []


def listAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    """Rows in id order for the Hive sync worker (cursor: id > after_id)."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, piece_uuid, request, provider, model, kind, rank, value_id, value_name, "
            "score, applied, created_at FROM piece_predictions WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def getMaxId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM piece_predictions").fetchone()
    return int(row["m"] or 0)
