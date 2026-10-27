"""Working out a piece's panel before anyone opens it.

The first open of a piece used to do the slow part itself: scoring its ~40
same-piece candidate crops with the link model (``piece_link_scores``) and
making its colour guesses (``piece_color_guesses``), seconds of storage reads
and model runs in the web process while the labeler waited. Both are kept per
piece once made, so the ``piece_warm`` job makes them ahead of time for the
pieces a grid page has just shown: when one is opened, the panel reads rows.

``enqueue_for_page`` is called by the grid's list request with the page's
pieces; it queues only the pieces missing either result for the active
models (two keyed reads), ahead of other background work, since a person is
looking at them.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.machine_piece_image import MachinePieceImage
from app.models.piece_model_output import PieceColorGuess, PieceLinkScore
from app.services import color_predictor, job_queue, link_predictor
from app.services.channel_crop_lookup import find_possible_crops
from app.services.job_queue import JobContext, PermanentJobError
from app.services.piece_color_guess import CropRef, color_guesses
from app.services.piece_link_scores import link_scores

logger = logging.getLogger(__name__)

KIND = "piece_warm"
# Ahead of live and backfill work: someone is looking at these pieces.
PRIORITY = 10


def _subject(machine_id: Any, piece_uuid: str) -> str:
    return f"{machine_id}|{piece_uuid}"


def enqueue_for_page(db: Session, rows: Iterable[Any]) -> int:
    """Queue piece_warm for the pieces of a page (queue rows: machine_id,
    piece_uuid, has_candidates) that lack the active colour model's guess, or
    the active link model's scores when they have same-piece candidates to
    score. Never raises: the page has been read already. Returns how many were
    queued."""
    rows = list(rows)
    keys = list(dict.fromkeys((r.machine_id, r.piece_uuid) for r in rows))
    with_candidates = {(r.machine_id, r.piece_uuid) for r in rows if r.has_candidates}
    if not keys:
        return 0
    try:
        machine_ids = list({k[0] for k in keys})
        piece_uuids = list({k[1] for k in keys})
        link = link_predictor.get_active(db)
        color = color_predictor.get_active(db)
        guessed = {
            (mid, puid)
            for mid, puid in db.query(PieceColorGuess.machine_id, PieceColorGuess.piece_uuid).filter(
                PieceColorGuess.model_sha256 == (color.sha256 if color is not None else ""),
                PieceColorGuess.machine_id.in_(machine_ids),
                PieceColorGuess.piece_uuid.in_(piece_uuids),
            )
        }
        scored = (
            {
                (mid, puid)
                for mid, puid in db.query(PieceLinkScore.machine_id, PieceLinkScore.piece_uuid).filter(
                    PieceLinkScore.model_sha256 == link.sha256,
                    PieceLinkScore.machine_id.in_(machine_ids),
                    PieceLinkScore.piece_uuid.in_(piece_uuids),
                )
            }
            if link is not None
            else set(keys)
        )
        missing = [k for k in keys if k not in guessed or (k in with_candidates and k not in scored)]
        if not missing:
            return 0
        return job_queue.enqueue_many(db, KIND, [_subject(*k) for k in missing], priority=PRIORITY)
    except Exception:
        db.rollback()
        logger.exception("could not queue piece_warm for a page")
        return 0


def warm(db: Session, machine_id: UUID, piece_uuid: str) -> dict[str, Any]:
    """Make the piece's colour guesses and link scores unless they are kept
    already (each function reads its kept row first, and commits before it
    reads storage)."""
    images = [
        CropRef(seq, key, bool(used), channel)
        for seq, key, used, channel in db.query(
            MachinePieceImage.seq, MachinePieceImage.image_key, MachinePieceImage.used, MachinePieceImage.channel
        )
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.image_key.isnot(None),
        )
        .order_by(MachinePieceImage.seq.asc())
    ]
    candidates = find_possible_crops(db, machine_id, piece_uuid)["candidates"]
    pixel, prediction = color_guesses(db, machine_id, piece_uuid, images)
    scores = link_scores(db, machine_id, piece_uuid, candidates)
    return {
        "guessed": pixel is not None,
        "predicted": prediction is not None,
        "scored": len(scores["scores"]) if scores else 0,
    }


def handle_piece_warm(job: JobContext) -> dict[str, Any]:
    try:
        machine_raw, piece_uuid = str(job.subject).split("|", 1)
        machine_id = UUID(machine_raw)
    except (ValueError, AttributeError) as exc:
        raise PermanentJobError(f"Not a piece: {job.subject!r}") from exc
    db = SessionLocal()
    try:
        return warm(db, machine_id, piece_uuid)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


job_queue.register_handler(KIND, handle_piece_warm, max_attempts=2, lease_s=300, backoff_s=60)
