"""The link model's scores for a piece's candidate crops, worked out once.

Scoring a piece reads its anchor crop and ~40 candidate crops from storage and
runs the model: 1 to 10 s when it was done in a row on every open. Now the
scores are kept per (piece, model sha256) in piece_link_scores, so a piece is
scored once per model, and a later open is a row read. Crops that synced after
the first open are scored on the next one and merged in.

The storage reads run concurrently and with no database transaction open.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.piece_model_output import PieceLinkScore
from app.services import link_predictor
from app.services.storage_backend import read_many


def _store(db: Session, machine_id: UUID, piece_uuid: str, model: link_predictor.ActiveLinkModel, scores: dict[int, float]) -> None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    values = {
        "machine_id": machine_id,
        "piece_uuid": piece_uuid,
        "model_sha256": model.sha256,
        "model_name": model.name,
        "scores": {str(k): v for k, v in scores.items()},
        "updated_at": datetime.now(timezone.utc),
    }
    stmt = insert(PieceLinkScore).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["machine_id", "piece_uuid", "model_sha256"],
        set_={"model_name": stmt.excluded.model_name, "scores": stmt.excluded.scores, "updated_at": stmt.excluded.updated_at},
    )
    db.execute(stmt)


def link_scores(db: Session, machine_id: UUID, piece_uuid: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """``{model_name, threshold, threshold_source, scores: {local_id: p}}`` for
    the active link model, or None when no model is active or nothing could be
    scored. ``candidates`` carry ``image_key`` (from find_possible_crops).

    Call it after every other read of the request: when crops need scoring it
    commits the transaction before reading storage."""
    model = link_predictor.active_model(db)
    if model is None:
        return None
    stored = (
        db.query(PieceLinkScore.scores)
        .filter(
            PieceLinkScore.machine_id == machine_id,
            PieceLinkScore.piece_uuid == piece_uuid,
            PieceLinkScore.model_sha256 == model.sha256,
        )
        .scalar()
    )
    scores = {int(k): float(v) for k, v in (stored or {}).items()}
    missing = [c for c in candidates if c.get("image_key") and int(c["local_id"]) not in scores]
    if missing:
        anchor = link_predictor.anchor_key(db, machine_id, piece_uuid)
        if anchor is not None:
            db.commit()
            data = read_many([anchor] + [c["image_key"] for c in missing])
            anchor_bytes = data.get(anchor)
            if anchor_bytes:
                fresh = link_predictor.score_crops(model, anchor_bytes, [(c, data.get(c["image_key"])) for c in missing])
                if fresh:
                    scores.update(fresh)
                    _store(db, machine_id, piece_uuid, model, scores)
                    db.commit()
    if not scores:
        return None
    return {
        "model_name": model.name,
        "threshold": model.threshold,
        "threshold_source": model.threshold_source,
        "scores": scores,
    }
