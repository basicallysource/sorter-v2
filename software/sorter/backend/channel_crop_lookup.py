"""'Possibly the same piece' lookup over the unlabeled C2/C3 channel crops.

Given the time T a piece arrived at the classification channel (C4), find the
upstream C2/C3 bbox crops that are plausibly the same physical piece — cheaply,
by time + channel + distance-to-exit, without embeddings or cross-channel
tracking.

The scoring model + all of its parameters live in channel_crop_lookup_params
(shared byte-for-byte with hive). This module runs that scorer over the local
crop store. The result is a SUPERSET ranked by confidence: the true crops are
(almost) always included; the top of the list is dominated by the correct piece.
"""

from __future__ import annotations

from typing import Any

import channel_crop_store
from channel_crop_lookup_params import DEFAULT_PARAMS, ChannelCropLookupParams, isPredicted, scoreCrop


def findPossibleCropsAt(
    arrival_ts: float, limit: int = 40, p: ChannelCropLookupParams = DEFAULT_PARAMS
) -> dict[str, Any]:
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
