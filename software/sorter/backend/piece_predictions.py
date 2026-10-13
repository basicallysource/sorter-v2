"""Every prediction made for a piece, from any source, kept and sent to Hive.

A prediction is one request's ranked answers: what a provider's model said a
piece is (its part, its colour, or both) from a set of the piece's images.
Two tables hold them:

- piece_prediction_requests: one row per prediction, saying where it came
  from. `source` is "live" for the classification the machine made while
  sorting, or the label of a later run over stored images (for example
  "colorpred-v4 rerun, 13 Oct"); `request` tells a source's requests apart
  (Brickognize's combined and single_burst calls and the hosted colour model's
  "hosted" call, live; a later run's model name); then the provider, the model
  (name and sha256 where there is one), the images it was made from and when.
- piece_predictions: the ranked answers under each request, one row per
  (kind, rank). Rows never change, so they sync to Hive by id, each carrying
  its request's fields.

A new source is data, not code: the live classification writes its requests
when the piece's classification settles (fromClassification), and a later run
imports its answers (importRun). Neither ever changes a row already written.

Images are referenced by their place in the piece's stored sets: "burst" is
the classification channel's crops (piece_image_store's piece_images, by seq),
"link" the upstream crops the piece-link model matched (piece_link_images, by
seq), each with the channel it was captured on.
"""

from __future__ import annotations

import json
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
KINDS = (KIND_PART, KIND_COLOR)
SOURCE_LIVE = "live"
REQUEST_HOSTED = "hosted"
IMAGE_SET_BURST = "burst"
IMAGE_SET_LINK = "link"

# Bounds on one imported run batch.
IMPORT_MAX_PIECES = 500
IMPORT_MAX_ANSWERS = 10
IMPORT_MAX_IMAGES = 32

# The latest pieces' predictions, so a piece still in the runtime lookup (whose
# detail the UI polls while sorting) is served without touching the database.
_RECENT_MAX = 2000
_recent_lock = threading.Lock()
_recent: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()

_REQUEST_COLUMNS = (
    "piece_uuid", "source", "request", "provider", "model_name", "model_sha", "images", "created_at",
)
_ANSWER_COLUMNS = (
    "request_id", "piece_uuid", "kind", "rank", "value_id", "value_name", "score", "applied", "created_at",
)


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS piece_prediction_requests ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "piece_uuid TEXT NOT NULL, "
        # "live", or the label of a later run over stored images.
        "source TEXT NOT NULL, "
        # Which of the source's requests: combined / single_burst / hosted
        # live, a later run's model name.
        "request TEXT NOT NULL, "
        "provider TEXT NOT NULL, "
        "model_name TEXT, "
        "model_sha TEXT, "
        # JSON list of {"set": "burst" | "link", "seq", "channel"}; NULL when
        # not recorded (predictions kept before images were).
        "images TEXT, "
        "created_at REAL NOT NULL, "
        "UNIQUE(piece_uuid, source, request)"
        ")"
    )
    if _isFlatTable(conn):
        _splitFlatTable(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS piece_predictions ("
        # The Hive sync cursor.
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "request_id INTEGER NOT NULL, "
        "piece_uuid TEXT NOT NULL, "
        "kind TEXT NOT NULL, "
        # 0-based, in the provider's own order.
        "rank INTEGER NOT NULL, "
        # A BrickLink colour id (as text) for a colour, a part number for a part.
        "value_id TEXT NOT NULL, "
        "value_name TEXT, "
        "score REAL, "
        # The one part and the one colour the piece took (live only).
        "applied INTEGER NOT NULL DEFAULT 0, "
        "created_at REAL NOT NULL, "
        "UNIQUE(request_id, kind, rank)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_piece_predictions_uuid ON piece_predictions(piece_uuid)"
    )


def _isFlatTable(conn: sqlite3.Connection) -> bool:
    """Whether piece_predictions still has its first shape: one flat row per
    answer, each repeating its request's fields."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(piece_predictions)")}
    return bool(columns) and "request_id" not in columns


def _splitFlatTable(conn: sqlite3.Connection) -> None:
    """Move the first shape's rows into requests and answers, once. Every
    answer keeps its id, and the id counter never goes back, so the watermark
    Hive holds for piece_predictions keeps meaning what it did. Their source
    is the live classification; which images they saw was not kept."""
    started = time.monotonic()
    conn.execute("SAVEPOINT split_piece_predictions")
    try:
        counter = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'piece_predictions'"
        ).fetchone()
        conn.execute("ALTER TABLE piece_predictions RENAME TO piece_predictions_flat")
        conn.execute("DROP INDEX IF EXISTS idx_piece_predictions_uuid")
        conn.execute(
            "INSERT OR IGNORE INTO piece_prediction_requests "
            "(piece_uuid, source, request, provider, model_name, model_sha, images, created_at) "
            "SELECT piece_uuid, ?, request, MIN(provider), NULL, MIN(model), NULL, MIN(created_at) "
            "FROM piece_predictions_flat GROUP BY piece_uuid, request ORDER BY MIN(id)",
            (SOURCE_LIVE,),
        )
        conn.execute(
            "CREATE TABLE piece_predictions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "request_id INTEGER NOT NULL, "
            "piece_uuid TEXT NOT NULL, "
            "kind TEXT NOT NULL, "
            "rank INTEGER NOT NULL, "
            "value_id TEXT NOT NULL, "
            "value_name TEXT, "
            "score REAL, "
            "applied INTEGER NOT NULL DEFAULT 0, "
            "created_at REAL NOT NULL, "
            "UNIQUE(request_id, kind, rank)"
            ")"
        )
        moved = conn.execute(
            "INSERT INTO piece_predictions "
            "(id, request_id, piece_uuid, kind, rank, value_id, value_name, score, applied, created_at) "
            "SELECT f.id, q.id, f.piece_uuid, f.kind, f.rank, f.value_id, f.value_name, f.score, "
            "f.applied, f.created_at FROM piece_predictions_flat f "
            "JOIN piece_prediction_requests q ON q.piece_uuid = f.piece_uuid "
            "AND q.source = ? AND q.request = f.request",
            (SOURCE_LIVE,),
        ).rowcount
        if counter is not None:
            # Ids handed out before and since removed (retention) stay used.
            conn.execute(
                "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'piece_predictions'",
                (int(counter[0]),),
            )
            if conn.execute(
                "SELECT 1 FROM sqlite_sequence WHERE name = 'piece_predictions'"
            ).fetchone() is None:
                conn.execute(
                    "INSERT INTO sqlite_sequence (name, seq) VALUES ('piece_predictions', ?)",
                    (int(counter[0]),),
                )
        conn.execute("DROP TABLE piece_predictions_flat")
        conn.execute("RELEASE split_piece_predictions")
    except Exception:
        conn.execute("ROLLBACK TO split_piece_predictions")
        conn.execute("RELEASE split_piece_predictions")
        raise
    db.note(
        f"[db] piece_predictions: {moved} answers moved under their requests "
        f"in {time.monotonic() - started:.1f}s"
    )


def _connection():
    return db.connect(_createTables)


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _images(images: Optional[Iterable[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
    if images is None:
        return None
    return [{"set": i.get("set"), "seq": i.get("seq"), "channel": i.get("channel")} for i in images]


def _imagesJson(images: Optional[Iterable[dict[str, Any]]]) -> Optional[str]:
    shaped = _images(images)
    return None if shaped is None else json.dumps(shaped, separators=(",", ":"))


def _imagesFromJson(raw: Any) -> Optional[list[dict[str, Any]]]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, list) else None


# --- the live classification -------------------------------------------------


def fromClassification(
    *,
    attempts: Iterable[Any],
    hosted: Optional[dict[str, Any]],
    applied_part: Optional[tuple[str, Optional[int]]],
    applied_color: Optional[tuple[str, Optional[str], Optional[int]]],
    hosted_images: Optional[list[dict[str, Any]]] = None,
    created_at: Optional[float] = None,
) -> list[dict[str, Any]]:
    """The live predictions for one piece, from its classification attempts
    (each with `label`, `applied`, `items` and `colors`: ranked dicts with id,
    name, score, rank; and `images`: the image references it sent) and the
    hosted colour model's answer (`top`: dicts with color_id, color_name,
    confidence; `model_name`, `model_sha256`), with the images sent to it.

    `applied_part` is (part id, Brickognize rank) of the part the piece took;
    `applied_color` is (provider, colour id, Brickognize rank) of its colour.
    A request that ranked nothing is left out."""
    now = float(created_at) if created_at is not None else time.time()
    predictions: list[dict[str, Any]] = []
    for attempt in attempts:
        label = getattr(attempt, "label", None) or getattr(getattr(attempt, "strategy", None), "value", None)
        if not label:
            continue
        took_this_request = bool(getattr(attempt, "applied", False))
        answers: list[dict[str, Any]] = []
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
                answers.append({
                    "kind": kind,
                    "rank": rank,
                    "value_id": value_id,
                    "value_name": str(entry["name"]) if entry.get("name") is not None else None,
                    "score": _num(entry.get("score")),
                    "applied": applied,
                })
        if answers:
            images = getattr(attempt, "images", None)
            predictions.append({
                "source": SOURCE_LIVE,
                "request": str(label),
                "provider": "brickognize",
                "model_name": None,
                "model_sha": None,
                "images": _images(images),
                "created_at": now,
                "answers": sorted(answers, key=lambda a: (a["kind"], a["rank"])),
            })
    if isinstance(hosted, dict):
        answers = []
        for rank, entry in enumerate((hosted.get("top") or [])[:HOSTED_COLORS]):
            if not isinstance(entry, dict) or entry.get("color_id") is None:
                continue
            value_id = str(entry["color_id"])
            answers.append({
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
            })
        if answers:
            model_name = hosted.get("model_name")
            model_sha = hosted.get("model_sha256")
            predictions.append({
                "source": SOURCE_LIVE,
                "request": REQUEST_HOSTED,
                "provider": "hive_basically",
                "model_name": str(model_name) if model_name else None,
                "model_sha": str(model_sha) if model_sha else None,
                "images": _images(hosted_images),
                "created_at": now,
                "answers": answers,
            })
    return predictions


def _insert(conn: sqlite3.Connection, piece_uuid: str, prediction: dict[str, Any]) -> int:
    """Store one prediction unless the piece already has its (source,
    request). Returns how many answers were added."""
    created_at = float(prediction.get("created_at") or time.time())
    cur = conn.execute(
        f"INSERT OR IGNORE INTO piece_prediction_requests ({', '.join(_REQUEST_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in _REQUEST_COLUMNS)})",
        (
            piece_uuid,
            str(prediction["source"]),
            str(prediction["request"]),
            str(prediction["provider"]),
            prediction.get("model_name"),
            prediction.get("model_sha"),
            _imagesJson(prediction.get("images")),
            created_at,
        ),
    )
    if not cur.rowcount:
        return 0
    request_id = int(cur.lastrowid)
    added = conn.executemany(
        f"INSERT OR IGNORE INTO piece_predictions ({', '.join(_ANSWER_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in _ANSWER_COLUMNS)})",
        [
            (
                request_id,
                piece_uuid,
                a["kind"],
                int(a["rank"]),
                str(a["value_id"]),
                a.get("value_name"),
                a.get("score"),
                1 if a.get("applied") else 0,
                created_at,
            )
            for a in prediction.get("answers") or []
        ],
    ).rowcount
    return int(added or 0)


def recordPredictions(piece_uuid: str, predictions: list[dict[str, Any]]) -> int:
    """Store a piece's predictions (fromClassification's shape). A piece
    classified again (a retry) adds nothing for a (source, request) it already
    has. Returns how many answers were added."""
    if not isinstance(piece_uuid, str) or not piece_uuid or not predictions:
        return 0
    with _connection() as conn:
        added = sum(_insert(conn, piece_uuid, p) for p in predictions)
        conn.commit()
    return added


# --- reading -----------------------------------------------------------------


def _sortKey(prediction: dict[str, Any]) -> tuple:
    # The live classification first, then later runs, oldest first.
    return (prediction["source"] != SOURCE_LIVE, prediction.get("created_at") or 0.0, prediction["source"])


def _shape(request: sqlite3.Row, answers: list[sqlite3.Row]) -> dict[str, Any]:
    return {
        "source": request["source"],
        "request": request["request"],
        "provider": request["provider"],
        "model_name": request["model_name"],
        "model_sha": request["model_sha"],
        "images": _imagesFromJson(request["images"]),
        "created_at": request["created_at"],
        "answers": [
            {
                "kind": a["kind"],
                "rank": int(a["rank"]),
                "value_id": a["value_id"],
                "value_name": a["value_name"],
                "score": a["score"],
                "applied": bool(a["applied"]),
            }
            for a in sorted(answers, key=lambda a: (a["kind"], int(a["rank"])))
        ],
    }


def listForPiece(piece_uuid: str) -> list[dict[str, Any]]:
    """A piece's predictions: the live ones first, in the order they were
    made, then each later run's; each with its answers by kind and rank."""
    with _connection() as conn:
        requests = conn.execute(
            "SELECT id, source, request, provider, model_name, model_sha, images, created_at "
            "FROM piece_prediction_requests WHERE piece_uuid = ? ORDER BY id",
            (piece_uuid,),
        ).fetchall()
        answers = conn.execute(
            "SELECT request_id, kind, rank, value_id, value_name, score, applied "
            "FROM piece_predictions WHERE piece_uuid = ?",
            (piece_uuid,),
        ).fetchall()
    by_request: dict[int, list[sqlite3.Row]] = {}
    for a in answers:
        by_request.setdefault(int(a["request_id"]), []).append(a)
    shaped = [_shape(q, by_request.get(int(q["id"]), [])) for q in requests]
    return sorted((p for p in shaped if p["answers"]), key=_sortKey)


def answersOf(predictions: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Every answer of one kind across predictions, flat."""
    return [a for p in predictions for a in p.get("answers") or [] if a.get("kind") == kind]


def remember(piece_uuid: str, predictions: list[dict[str, Any]]) -> None:
    """Keep a just-classified piece's predictions in memory (see _recent)."""
    shaped = sorted(
        (
            {
                **{k: p.get(k) for k in ("source", "request", "provider", "model_name", "model_sha", "created_at")},
                "images": _images(p.get("images")),
                "answers": sorted(
                    ({k: a.get(k) for k in ("kind", "rank", "value_id", "value_name", "score", "applied")}
                     for a in p.get("answers") or []),
                    key=lambda a: (a["kind"], a["rank"]),
                ),
            }
            for p in predictions
            if p.get("answers")
        ),
        key=_sortKey,
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
        predictions = _recent.get(piece_uuid)
    if not predictions:
        return []
    return [{**p, "answers": [dict(a) for a in p["answers"]]} for p in predictions]


def _refreshRecent(piece_uuids: Iterable[str]) -> None:
    # A piece still in memory gained predictions: serve the stored ones.
    with _recent_lock:
        held = [u for u in piece_uuids if u in _recent]
    for piece_uuid in held:
        stored = listForPiece(piece_uuid)
        with _recent_lock:
            if piece_uuid in _recent:
                _recent[piece_uuid] = stored


# --- the Hive sync -----------------------------------------------------------


def listAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    """Answers in id order for the Hive sync worker (cursor: id > after_id),
    each with its request's fields."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT a.id, a.piece_uuid, q.source, q.request, q.provider, q.model_name, q.model_sha, "
            "q.images, a.kind, a.rank, a.value_id, a.value_name, a.score, a.applied, a.created_at "
            "FROM piece_predictions a JOIN piece_prediction_requests q ON q.id = a.request_id "
            "WHERE a.id > ? ORDER BY a.id ASC LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        row["images"] = _imagesFromJson(row["images"])
        out.append(row)
    return out


def getMaxId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM piece_predictions").fetchone()
    return int(row["m"] or 0)


# --- runs over stored images -------------------------------------------------


def importRun(
    *,
    source: str,
    provider: str,
    model_name: str,
    model_sha: Optional[str],
    kind: str,
    pieces: list[dict[str, Any]],
    made_at: Optional[float] = None,
) -> dict[str, Any]:
    """Keep a later run's predictions: one model over pieces' stored images.
    Each piece is {"piece_uuid", "answers": [{"value_id", "value_name",
    "score"}] best first, "image_seqs": burst seqs, "link_image_seqs": link
    seqs}. Idempotent per (piece, source, model name): a piece that already
    has this run's prediction is left as it is. A piece this machine has no
    record or images of is not kept. Returns the pieces added, already there
    and unknown."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if source == SOURCE_LIVE:
        raise ValueError(f"source {SOURCE_LIVE!r} is the live classification's")
    if len(pieces) > IMPORT_MAX_PIECES:
        raise ValueError(f"at most {IMPORT_MAX_PIECES} pieces a batch")
    created_at = float(made_at) if made_at is not None else time.time()
    added: list[str] = []
    already: list[str] = []
    unknown: list[str] = []
    import piece_records  # its schema holds the piece, image and prediction tables

    with db.connect(piece_records._createTables) as conn:
        for piece in pieces:
            piece_uuid = str(piece["piece_uuid"])
            burst = {
                int(r["seq"]): r["channel"]
                for r in conn.execute("SELECT seq, channel FROM piece_images WHERE piece_uuid = ?", (piece_uuid,))
            }
            if not burst and conn.execute(
                "SELECT 1 FROM piece_records WHERE uuid = ?", (piece_uuid,)
            ).fetchone() is None:
                unknown.append(piece_uuid)
                continue
            link = {
                int(r["seq"]): r["channel"]
                for r in conn.execute("SELECT seq, channel FROM piece_link_images WHERE piece_uuid = ?", (piece_uuid,))
            } if piece.get("link_image_seqs") else {}
            images = [
                {"set": IMAGE_SET_BURST, "seq": int(seq), "channel": burst.get(int(seq))}
                for seq in piece.get("image_seqs") or []
            ] + [
                {"set": IMAGE_SET_LINK, "seq": int(seq), "channel": link.get(int(seq))}
                for seq in piece.get("link_image_seqs") or []
            ]
            prediction = {
                "source": source,
                "request": model_name,
                "provider": provider,
                "model_name": model_name,
                "model_sha": model_sha,
                "images": images,
                "created_at": created_at,
                "answers": [
                    {
                        "kind": kind,
                        "rank": rank,
                        "value_id": str(a["value_id"]),
                        "value_name": a.get("value_name"),
                        "score": _num(a.get("score")),
                        "applied": False,
                    }
                    for rank, a in enumerate(piece.get("answers") or [])
                ],
            }
            (added if _insert(conn, piece_uuid, prediction) else already).append(piece_uuid)
        conn.commit()
    _refreshRecent(added)
    return {"added": len(added), "already": len(already), "unknown": unknown}
