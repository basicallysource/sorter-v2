"""'Possibly the same piece' lookup over the unlabeled C2/C3 channel crops.

Given a classified piece (which we saw arrive at the classification channel / C4
at time T), find the upstream C2/C3 bbox crops that are plausibly the same
physical piece — cheaply, by time + channel + distance-to-exit, without
embeddings or cross-channel tracking.

The scoring model + all of its parameters live in channel_crop_lookup_params
(shared byte-for-byte with hive). This module just resolves the piece's arrival
time and runs that scorer over the local crop store. The result is a SUPERSET
ranked by confidence: the true crops are (almost) always included; the top of
the list is dominated by the correct piece.
"""

from __future__ import annotations

from typing import Any, Optional

import channel_crop_store
from channel_crop_lookup_params import DEFAULT_PARAMS, ChannelCropLookupParams, isPredicted, scoreCrop


def _arrivalTs(gc: Any, piece_uuid: str, p: ChannelCropLookupParams) -> Optional[float]:
    # When the piece reached the classification channel: earliest C4 crop ts,
    # else earliest crop ts of any kind, else the piece record's seen_at.
    try:
        import piece_image_store

        images = piece_image_store.listPieceImages(piece_uuid)
        c4 = [im["ts"] for im in images if im.get("channel") == p.classification_channel_id and im.get("ts")]
        if c4:
            return float(min(c4))
        any_ts = [im["ts"] for im in images if im.get("ts")]
        if any_ts:
            return float(min(any_ts))
    except Exception:
        pass
    try:
        import piece_records

        summary = piece_records.getPieceSummaryByUuid(gc, piece_uuid)
        seen = summary.get("seen_at") if isinstance(summary, dict) else None
        if isinstance(seen, (int, float)):
            return float(seen)
    except Exception:
        pass
    return None


def findPossibleCrops(
    gc: Any, piece_uuid: str, limit: int = 40, p: ChannelCropLookupParams = DEFAULT_PARAMS
) -> dict[str, Any]:
    arrival_ts = _arrivalTs(gc, piece_uuid, p)
    if arrival_ts is None:
        return {"arrival_ts": None, "candidates": []}
    crops = channel_crop_store.listCropsByTimeRange(arrival_ts - p.lookback_window_s, arrival_ts + p.fwd_slop_s)
    scored: list[dict[str, Any]] = []
    for crop in crops:
        s = scoreCrop(crop, arrival_ts, p)
        if s is None:
            continue
        scored.append(
            {
                "id": crop["id"],
                "channel": crop["channel"],
                "ts": crop["ts"],
                "dt": round(arrival_ts - crop["ts"], 2),
                "zone_code": crop["zone_code"],
                "com_forward_to_exit_deg": crop["com_forward_to_exit_deg"],
                "track_id": crop["track_id"],
                "sharpness": crop["sharpness"],
                "score": round(s, 3),
                "predicted": isPredicted(s, p),
            }
        )
    scored.sort(key=lambda c: c["score"], reverse=True)
    return {"arrival_ts": arrival_ts, "candidates": scored[:limit]}
