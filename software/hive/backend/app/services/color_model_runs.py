"""Every colour model's answer for a piece, kept for sorting and for comparing.

The ``color_model_run`` job runs one colour model (a file in COLOR_MODEL_DIR,
named by its sha256) over a batch of one machine's pieces, the way the piece
panel's guess is made: the piece's chosen crops (``piece_color_guess.chosen_crops``),
each resized to the model's input, the mean softmax over them (a multiview
model gets each crop's camera channel). It keeps the top colour, its
confidence and the top three per (machine, piece, model sha256) in
``piece_model_colors``, so every model's answers stay side by side as new
models are added.

``backfill`` queues it for every model in the registry (or the ones named)
over a machine's queued pieces, all of them or a filter's worth (the colour
reference palette near them, same-piece candidates), BATCH pieces a job,
behind live work. Each model's batches are queued together, and the job keeps
one model's session at a time (one thread, no memory arena), so a backfill
loads each model once.

The piece grid sorts by a model's confidence (``services/review_queue.py``)
and its cards show the model's colour; the piece panel lists every model's
answer for the piece (``answers_for_piece``).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence
from uuid import UUID

import numpy as np
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.color_model import ColorModel
from app.models.labeling_queue import LabelingQueueEntry
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.piece_model_output import PieceModelColor
from app.services import color_predictor, job_queue
from app.services.job_queue import JobContext, PermanentJobError
from app.services.piece_color_guess import CropRef, chosen_crops
from app.services.profile_catalog import get_profile_catalog_service
from app.services.storage_backend import read_many

logger = logging.getLogger(__name__)

KIND = "color_model_run"
# Pieces per job: their crops are read from storage at once, a few MB.
BATCH = 20
# Behind live work, beside the swatch backfill.
BACKFILL_PRIORITY = -10
BACKFILL_MAX = 50_000
_IN_CHUNK = 500


def _chunks(items: Sequence[Any], size: int = _IN_CHUNK) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# --- Running a model -------------------------------------------------------------

_slot_lock = threading.Lock()
_slot: tuple[str, Any] | None = None


def _model(filename: str, sha256: str):
    """The model's session: one at a time, on one thread without a memory
    arena, since the worker shares a small box with the API."""
    global _slot
    with _slot_lock:
        if _slot is not None and _slot[0] == sha256:
            return _slot[1]
    loaded = color_predictor.load_file(filename, threads=1, low_memory=True)
    if loaded is None:
        return None
    with _slot_lock:
        _slot = (sha256, loaded)
    return loaded


def answer(loaded: Any, blobs: list[bytes], channels: list[int]) -> dict[str, Any] | None:
    """A model's answer for one piece's crops: ``{color_id, confidence, top}``,
    top being the three likeliest ``{color_id, confidence}``; None when no crop
    decodes."""
    probs = color_predictor.class_probabilities(loaded, blobs, channels)
    if probs is None:
        return None
    order = [int(i) for i in np.argsort(-probs)[:3] if int(i) < len(loaded.class_ids)]
    if not order:
        return None
    top = [{"color_id": int(loaded.class_ids[i]), "confidence": round(float(probs[i]), 4)} for i in order]
    return {"color_id": top[0]["color_id"], "confidence": float(probs[order[0]]), "top": top}


def _store(db: Session, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(PieceModelColor).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["machine_id", "piece_uuid", "model_sha256"],
        set_={col: getattr(stmt.excluded, col) for col in ("model_name", "color_id", "confidence", "top", "seqs", "created_at")},
    )
    db.execute(stmt)


def run_batch(db: Session, model_sha256: str, machine_id: UUID, piece_uuids: list[str]) -> dict[str, Any]:
    """Run one model over some of a machine's pieces and keep its answers.
    The reads are committed before storage is read and the model runs, so no
    transaction is open meanwhile; the answers are written after."""
    row = db.query(ColorModel.filename, ColorModel.name).filter(ColorModel.sha256 == model_sha256).first()
    if row is None:
        raise PermanentJobError("No colour model with this sha256 is in the registry.")
    filename, name = row.filename, row.name
    crops: dict[str, list[CropRef]] = defaultdict(list)
    for puid, seq, key, used, channel in (
        db.query(
            MachinePieceImage.piece_uuid,
            MachinePieceImage.seq,
            MachinePieceImage.image_key,
            MachinePieceImage.used,
            MachinePieceImage.channel,
        )
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid.in_(piece_uuids),
            MachinePieceImage.image_key.isnot(None),
        )
        .order_by(MachinePieceImage.piece_uuid, MachinePieceImage.seq)
    ):
        crops[puid].append(CropRef(seq, key, bool(used), channel))
    db.commit()

    loaded = _model(filename, model_sha256)
    if loaded is None:
        # The file may come back (a copy in progress): retried with a backoff.
        raise RuntimeError(f"Colour model {filename} is missing from the model folder or does not load.")
    chosen = {puid: chosen_crops(refs) for puid, refs in crops.items()}
    data = read_many([im.image_key for refs in chosen.values() for im in refs])

    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for puid, refs in chosen.items():
        readable = [(im, data.get(im.image_key)) for im in refs]
        readable = [(im, blob) for im, blob in readable if blob]
        if not readable:
            continue
        result = answer(loaded, [blob for _, blob in readable], [im.channel or 4 for im, _ in readable])
        if result is None:
            continue
        rows.append(
            {
                "machine_id": machine_id,
                "piece_uuid": puid,
                "model_sha256": model_sha256,
                "model_name": name,
                "color_id": result["color_id"],
                "confidence": result["confidence"],
                "top": result["top"],
                "seqs": [im.seq for im, _ in readable],
                "created_at": now,
            }
        )
    del data

    # Pieces deleted while the batch ran are left out (their rows would break
    # the foreign key and fail the whole batch).
    existing = {
        puid
        for (puid,) in db.query(MachinePiece.piece_uuid).filter(
            MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid.in_([r["piece_uuid"] for r in rows] or [""])
        )
    }
    rows = [r for r in rows if r["piece_uuid"] in existing]
    _store(db, rows)
    db.commit()
    return {"model": name, "pieces": len(piece_uuids), "answered": len(rows)}


def handle_color_model_run(job: JobContext) -> dict[str, Any]:
    payload = job.payload or {}
    try:
        sha = str(payload["model_sha256"])
        machine_id = UUID(str(payload["machine_id"]))
        pieces = [str(p) for p in payload["pieces"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentJobError(f"Not a colour model run: {payload!r}") from exc
    if not pieces:
        return {"pieces": 0, "answered": 0}
    db = SessionLocal()
    try:
        return run_batch(db, sha, machine_id, pieces)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


job_queue.register_handler(KIND, handle_color_model_run, max_attempts=3, lease_s=600, backoff_s=60)


# --- Queueing ----------------------------------------------------------------------


def registry(db: Session) -> list[ColorModel]:
    """The registered colour models, the active one first, then newest first."""
    return (
        db.query(ColorModel)
        .order_by(ColorModel.is_active.desc(), ColorModel.created_at.desc(), ColorModel.name.desc())
        .all()
    )


def backfill(
    db: Session,
    *,
    machine_id: UUID,
    model_sha256s: list[str] | None = None,
    with_palette: bool = False,
    with_candidates: bool = False,
    rerun: bool = False,
    limit: int = BACKFILL_MAX,
) -> dict[str, Any]:
    """Queue every registered colour model (or the ones named) over one
    machine's queued pieces, newest first, or only those with the palette near
    them or with same-piece candidates. A piece a model has already answered
    is left out unless ``rerun``; a batch already queued is not queued twice.
    Each model's batches are queued together."""
    models = registry(db)
    if model_sha256s:
        wanted = set(model_sha256s)
        unknown = wanted - {m.sha256 for m in models}
        if unknown:
            raise ValueError(f"No colour model with sha256 {sorted(unknown)[0]} is in the registry.")
        models = [m for m in models if m.sha256 in wanted]
    limit = max(1, min(int(limit), BACKFILL_MAX))
    q = db.query(LabelingQueueEntry.piece_uuid).filter(LabelingQueueEntry.machine_id == machine_id)
    if with_palette:
        q = q.filter(LabelingQueueEntry.has_palette.is_(True))
    if with_candidates:
        q = q.filter(LabelingQueueEntry.has_candidates.is_(True))
    pieces = [puid for (puid,) in q.order_by(LabelingQueueEntry.arrival_at.desc()).limit(limit)]

    out = []
    for model in models:
        todo = pieces
        if not rerun:
            done = {
                puid
                for (puid,) in db.query(PieceModelColor.piece_uuid).filter(
                    PieceModelColor.machine_id == machine_id, PieceModelColor.model_sha256 == model.sha256
                )
            }
            todo = [p for p in pieces if p not in done]
        jobs = 0
        for batch in _chunks(todo, BATCH):
            subject = f"{model.sha256}:{machine_id}:{hashlib.sha256(','.join(batch).encode()).hexdigest()[:16]}"
            payload = {"model_sha256": model.sha256, "machine_id": str(machine_id), "pieces": list(batch)}
            if job_queue.enqueue(db, KIND, subject, payload, priority=BACKFILL_PRIORITY, commit=False):
                jobs += 1
        out.append({"name": model.name, "sha256": model.sha256, "pieces": len(todo), "jobs": jobs})
    db.commit()
    return {"pieces": len(pieces), "truncated": len(pieces) >= limit, "models": out}


# --- Reading -------------------------------------------------------------------------


def _palette() -> dict[int, dict[str, Any]]:
    return {
        c["id"]: c
        for c in get_profile_catalog_service().list_bricklink_colors()
        if isinstance(c.get("id"), int)
    }


def _color(color_id: int, palette: dict[int, dict[str, Any]]) -> dict[str, Any]:
    c = palette.get(color_id) or {}
    return {"color_id": color_id, "color_name": c.get("name"), "rgb": (c.get("rgb") or "").replace("#", "") or None}


def menu(db: Session) -> list[dict[str, Any]]:
    """The models a person can sort and compare by, the active one first."""
    return [
        {"sha256": m.sha256, "name": m.name, "filename": m.filename, "is_active": bool(m.is_active)}
        for m in registry(db)
    ]


def active_sha256(db: Session) -> str | None:
    row = db.query(ColorModel.sha256).filter(ColorModel.is_active.is_(True)).first()
    return row[0] if row else None


def answers_for_cards(db: Session, keys: set[tuple[Any, str]], model_sha256: str) -> dict[tuple[Any, str], dict[str, Any]]:
    """One model's answers for a page of pieces: a keyed read."""
    if not keys:
        return {}
    machine_ids = list({k[0] for k in keys})
    piece_uuids = list({k[1] for k in keys})
    palette = None
    out: dict[tuple[Any, str], dict[str, Any]] = {}
    for row in db.query(PieceModelColor.machine_id, PieceModelColor.piece_uuid, PieceModelColor.color_id, PieceModelColor.confidence).filter(
        PieceModelColor.model_sha256 == model_sha256,
        PieceModelColor.machine_id.in_(machine_ids),
        PieceModelColor.piece_uuid.in_(piece_uuids),
    ):
        key = (row.machine_id, row.piece_uuid)
        if key not in keys:
            continue
        if palette is None:
            palette = _palette()
        out[key] = {**_color(row.color_id, palette), "confidence": float(row.confidence)}
    return out


def answers_for_piece(db: Session, machine_id: UUID, piece_uuid: str) -> list[dict[str, Any]]:
    """Every stored model answer for a piece, in the menu's order (the active
    model first, then newest first); a removed model's answers last, newest
    first, under the name it had."""
    rows = db.query(PieceModelColor).filter(
        PieceModelColor.machine_id == machine_id, PieceModelColor.piece_uuid == piece_uuid
    ).all()
    if not rows:
        return []
    order = {m["sha256"]: (i, m) for i, m in enumerate(menu(db))}
    palette = _palette()
    rows.sort(
        key=lambda r: (
            order[r.model_sha256][0] if r.model_sha256 in order else len(order),
            -(r.created_at.timestamp() if r.created_at else 0.0),
        )
    )
    return [
        {
            "model_sha256": r.model_sha256,
            "model_name": order[r.model_sha256][1]["name"] if r.model_sha256 in order else r.model_name,
            "is_active": bool(order[r.model_sha256][1]["is_active"]) if r.model_sha256 in order else False,
            **_color(r.color_id, palette),
            "confidence": float(r.confidence),
            "top": [{**_color(int(t["color_id"]), palette), "confidence": float(t["confidence"])} for t in r.top or []],
            "crops": len(r.seqs or []),
            "at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
