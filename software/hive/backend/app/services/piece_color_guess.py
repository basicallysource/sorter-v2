"""A piece's pixel-average colour and colour-model prediction, worked out once.

Both come from the same crops: every crop the classification camera (C4) took
of the piece, at most MAX_SAMPLES. They used to be computed on every open of the piece, each reading the crops
from storage separately. Now the crops are read once, concurrently and with no
transaction open, both guesses are made from the same bytes, and the result is
kept per (piece, colour model sha256) in piece_color_guesses. It is made again
when the active model changes or the piece's usable crops do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.piece_model_output import PieceColorGuess
from app.services import color_predictor, pixel_color
from app.services.storage_backend import read_many

# As many as the colour model reads (a C4 burst is at most 8 frames).
MAX_SAMPLES = color_predictor.MAX_PREDICT_IMAGES


@dataclass(frozen=True)
class CropRef:
    seq: int
    image_key: str | None
    used: bool
    channel: int | None


def chosen_crops(images: list[CropRef]) -> list[CropRef]:
    """The crops a piece's colour is judged from: every one the classification
    camera (C4) took, in burst order, else every one in storage, at most
    MAX_SAMPLES. Not only the ones the machine used: those were picked for
    recognising the part, are often a single frame, and are sometimes an empty
    one, which alone decided the colour. The colour model runs
    (services.color_model_runs) read the same ones, so a model's answer for a
    piece is the same number wherever it shows."""
    with_key = sorted((im for im in images if im.image_key), key=lambda im: im.seq)
    c4 = [im for im in with_key if im.channel in (None, 4)]
    return (c4 or with_key)[:MAX_SAMPLES]


def color_guesses(db: Session, machine_id: UUID, piece_uuid: str, images: list[CropRef]) -> tuple[dict | None, dict | None]:
    """(pixel_guess, model_prediction) for a piece. Call it after the request's
    other reads: when the guess has to be made it commits before reading storage."""
    chosen = chosen_crops(images)
    if not chosen:
        return None, None
    model = color_predictor.get_active(db)
    sha = model.sha256 if model is not None else ""
    seqs = [im.seq for im in chosen]
    stored = (
        db.query(PieceColorGuess)
        .filter(
            PieceColorGuess.machine_id == machine_id,
            PieceColorGuess.piece_uuid == piece_uuid,
            PieceColorGuess.model_sha256 == sha,
        )
        .first()
    )
    if stored is not None and list(stored.seqs or []) == seqs:
        return stored.pixel_guess, stored.model_prediction

    db.commit()
    data = read_many([im.image_key for im in chosen])
    readable = [(im, data.get(im.image_key)) for im in chosen]
    readable = [(im, b) for im, b in readable if b]
    pixel = pixel_color.guess_from_bytes([b for _, b in readable])
    prediction = (
        _model_prediction(db, [b for _, b in readable], [im.channel or 4 for im, _ in readable])
        if model is not None and readable
        else None
    )
    # Keep it only when it is complete: a crop that failed to read, or a model
    # that failed to load, is tried again on the next open.
    if pixel is not None and (model is None or prediction is not None):
        _store(db, machine_id, piece_uuid, sha, seqs, pixel, prediction)
        db.commit()
    return pixel, prediction


def _model_prediction(db: Session, blobs: list[bytes], channels: list[int]) -> dict[str, Any] | None:
    result = color_predictor.predict_bytes(db, blobs, channels)
    if result is None:
        return None
    keep = ("method", "model_name", "color_id", "color_name", "rgb", "confidence", "sample_count", "top")
    return {k: result.get(k) for k in keep}


def _store(db: Session, machine_id: UUID, piece_uuid: str, sha: str, seqs: list[int], pixel: dict, prediction: dict | None) -> None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(PieceColorGuess).values(
        machine_id=machine_id,
        piece_uuid=piece_uuid,
        model_sha256=sha,
        seqs=seqs,
        pixel_guess=pixel,
        model_prediction=prediction,
        created_at=datetime.now(timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["machine_id", "piece_uuid", "model_sha256"],
        set_={
            "seqs": stmt.excluded.seqs,
            "pixel_guess": stmt.excluded.pixel_guess,
            "model_prediction": stmt.excluded.model_prediction,
            "created_at": stmt.excluded.created_at,
        },
    )
    db.execute(stmt)
