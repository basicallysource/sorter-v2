"""'Possibly the same piece' lookup over the unlabeled C2/C3 channel crops.

Given a classified piece (which we saw arrive at the classification channel / C4
at time T), find the upstream C2/C3 bbox crops that are plausibly the same
physical piece — cheaply, by time + channel + distance-to-exit, without
embeddings or cross-channel tracking.

Model (calibrated on a real kitbash run, 19 pieces traced by eye):
  - A piece is reliably captured in the C3 exit/precise band (small COM-to-exit
    degrees) ~0.2..7s before its C4 arrival (median ~3s; up to ~13s if it
    stalls). This is 'the bbox that just disappeared' — highest confidence.
  - Its earlier C3 crops (mid/drop, larger degrees) extend back to ~T-18s,
    progressively contaminated by the pieces queued behind it.
  - C2 rarely contains the specific piece within the window; keep a wide,
    low-weight net so we don't exclude it when present (superset), expect noise.
  - Track ids are unreliable (often absent, reused across pieces) — not used.

The result is a SUPERSET ranked by confidence: the true crops are (almost)
always included; the top of the list is dominated by the correct piece.
"""

from __future__ import annotations

from typing import Any, Optional

import channel_crop_store

CLASSIFICATION_CHANNEL_ID = 4

ZONE_EXIT = 2
ZONE_PRECISE = 3
EXIT_DEG = 20.0
C3_EXIT_LOOKBACK = 16.0
C3_LOOKBACK = 22.0
C2_LOOKBACK = 60.0
FWD_SLOP = 1.5
PEAK_DT = 3.0


def _atExit(zone: Optional[int], deg: Optional[float]) -> bool:
    return zone in (ZONE_EXIT, ZONE_PRECISE) or (deg is not None and abs(deg) < EXIT_DEG)


def scoreCrop(crop: dict[str, Any], arrival_ts: float) -> Optional[float]:
    ts = crop.get("ts")
    if ts is None:
        return None
    dt = arrival_ts - ts
    if dt < -FWD_SLOP:
        return None
    channel = crop.get("channel")
    zone = crop.get("zone_code")
    deg = crop.get("com_forward_to_exit_deg")
    if channel == 3:
        if _atExit(zone, deg) and dt <= C3_EXIT_LOOKBACK:
            return max(0.5, 0.9 - abs(dt - PEAK_DT) * 0.028)
        if dt <= C3_LOOKBACK:
            return max(0.15, 0.5 - dt * 0.014)
        return None
    if channel == 2:
        if 2.0 <= dt <= C2_LOOKBACK:
            return max(0.05, 0.32 - dt * 0.003)
        return None
    return None


def _arrivalTs(gc: Any, piece_uuid: str) -> Optional[float]:
    # When the piece reached the classification channel: earliest C4 crop ts,
    # else earliest crop ts of any kind, else the piece record's seen_at.
    try:
        import piece_image_store

        images = piece_image_store.listPieceImages(piece_uuid)
        c4 = [im["ts"] for im in images if im.get("channel") == CLASSIFICATION_CHANNEL_ID and im.get("ts")]
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


def findPossibleCrops(gc: Any, piece_uuid: str, limit: int = 40) -> dict[str, Any]:
    arrival_ts = _arrivalTs(gc, piece_uuid)
    if arrival_ts is None:
        return {"arrival_ts": None, "candidates": []}
    crops = channel_crop_store.listCropsByTimeRange(arrival_ts - C2_LOOKBACK, arrival_ts + FWD_SLOP)
    scored: list[dict[str, Any]] = []
    for crop in crops:
        s = scoreCrop(crop, arrival_ts)
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
            }
        )
    scored.sort(key=lambda c: c["score"], reverse=True)
    return {"arrival_ts": arrival_ts, "candidates": scored[:limit]}
