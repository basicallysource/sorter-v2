"""'Possibly the same piece' lookup over synced machine_channel_crops.

Hive-side analog of the sorter's channel_crop_lookup.py. Given a classified
synced piece (machine_id, piece_uuid), resolve when it arrived at the
classification channel (C4) and run the shared scorer over that machine's
upstream C2/C3 crops to surface a confidence-ranked SUPERSET of "possibly the
same piece" candidates. The scoring model + params are shared byte-for-byte with
the sorter (see channel_crop_lookup_params).

Timestamps in Postgres are tz-aware datetimes; scoring works in epoch seconds,
so we convert at the boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.services.channel_crop_lookup_params import DEFAULT_PARAMS, ChannelCropLookupParams, isPredicted, scoreCrop


def _epoch(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _arrival_ts(db: Session, machine_id: UUID, piece_uuid: str) -> Optional[float]:
    # When the piece reached the classification channel: earliest C4 crop ts,
    # else earliest crop ts of any kind, else the piece record's seen_at, else
    # recorded_at.
    c4_ts = (
        db.query(func.min(MachinePieceImage.ts))
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.channel == DEFAULT_PARAMS.classification_channel_id,
        )
        .scalar()
    )
    if c4_ts is not None:
        return _epoch(c4_ts)
    any_ts = (
        db.query(func.min(MachinePieceImage.ts))
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
        )
        .scalar()
    )
    if any_ts is not None:
        return _epoch(any_ts)
    piece = (
        db.query(MachinePiece.seen_at, MachinePiece.recorded_at)
        .filter(MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid == piece_uuid)
        .first()
    )
    if piece is not None:
        return _epoch(piece.seen_at) or _epoch(piece.recorded_at)
    return None


def find_possible_crops(
    db: Session,
    machine_id: UUID,
    piece_uuid: str,
    limit: int = 60,
    p: ChannelCropLookupParams = DEFAULT_PARAMS,
) -> dict[str, Any]:
    arrival_ts = _arrival_ts(db, machine_id, piece_uuid)
    if arrival_ts is None:
        return {"arrival_ts": None, "candidates": []}
    lo = datetime.fromtimestamp(arrival_ts - p.lookback_window_s, tz=timezone.utc)
    hi = datetime.fromtimestamp(arrival_ts + p.fwd_slop_s, tz=timezone.utc)
    rows = (
        db.query(MachineChannelCrop)
        .filter(
            MachineChannelCrop.machine_id == machine_id,
            MachineChannelCrop.ts.isnot(None),
            MachineChannelCrop.ts >= lo,
            MachineChannelCrop.ts <= hi,
        )
        .all()
    )
    scored: list[dict[str, Any]] = []
    for row in rows:
        ts = _epoch(row.ts)
        crop = {
            "channel": row.channel,
            "ts": ts,
            "zone_code": row.zone_code,
            "com_forward_to_exit_deg": row.com_forward_to_exit_deg,
        }
        s = scoreCrop(crop, arrival_ts, p)
        if s is None:
            continue
        scored.append(
            {
                "local_id": row.local_id,
                "channel": row.channel,
                "ts": row.ts.isoformat() if row.ts else None,
                "dt": round(arrival_ts - ts, 2) if ts is not None else None,
                "zone_code": row.zone_code,
                "com_forward_to_exit_deg": row.com_forward_to_exit_deg,
                "sharpness": row.sharpness,
                "score": round(s, 3),
                "predicted": isPredicted(s, p),
                "available": row.image_key is not None,
            }
        )
    scored.sort(key=lambda c: c["score"], reverse=True)
    return {
        "arrival_ts": datetime.fromtimestamp(arrival_ts, tz=timezone.utc).isoformat(),
        "candidates": scored[:limit],
    }
