"""Parameters + scoring for the 'possibly the same piece' crop lookup.

This is the single source of truth for HOW we decide, from time + channel +
distance-to-exit alone (no embeddings, no cross-channel track ids), which
upstream C2/C3 crops are plausibly the same physical piece as a classified
piece. It is a pure, dependency-free module so it can be copied verbatim.

ANALOG — an identical copy of this file lives in the other project. Keep the two
byte-for-byte in sync (same fields, same defaults, same scoring):
  - sorter:  software/sorter/backend/channel_crop_lookup_params.py
  - hive:    software/hive/backend/app/services/channel_crop_lookup_params.py
The sorter runs it over its local sqlite crop store to power the tracked-piece
page; hive runs it over the synced machine_channel_crops to power the
color-labeling page's same-piece suggestions. Both feed the same eventual
training target, so the presented candidates must match on both sides.

Model (calibrated on a real kitbash run, 19 pieces traced by eye):
  - A piece is reliably captured in the C3 exit/precise band (small COM-to-exit
    degrees) ~0.2..7s before its C4 arrival (median ~3s; up to ~13s if it
    stalls). Highest confidence — 'the bbox that just disappeared'.
  - Its earlier C3 crops (mid/drop, larger degrees) extend back ~18s,
    progressively contaminated by the pieces queued behind it.
  - C2 rarely contains the specific piece within the window; keep a wide,
    low-weight net so we don't exclude it when present (superset), expect noise.

scoreCrop returns a confidence in [0, ~0.9] or None (out of window / wrong
channel). isPredicted decides which candidates are pre-selected as the machine's
"same piece" guess (the rest are shown but unchecked).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ChannelCropLookupParams:
    # The channel a piece arrives at to be classified (its arrival ts anchors dt).
    classification_channel_id: int = 4
    # zone_code values that mean the piece is at/near the exit.
    zone_exit: int = 2
    zone_precise: int = 3
    # |com_forward_to_exit_deg| below this also counts as "at exit" when the zone
    # code is missing/coarse.
    exit_deg: float = 20.0
    # Lookback windows (seconds before arrival) per channel/band.
    c3_exit_lookback_s: float = 16.0
    c3_lookback_s: float = 22.0
    c2_lookback_s: float = 60.0
    # Allow crops up to this many seconds AFTER the anchor (timestamp jitter).
    fwd_slop_s: float = 1.5
    # C3 exit-band confidence peaks this many seconds before arrival.
    peak_dt_s: float = 3.0
    # C3 exit band scoring: peak - |dt - peak_dt| * falloff, floored.
    c3_exit_peak: float = 0.9
    c3_exit_falloff_per_s: float = 0.028
    c3_exit_floor: float = 0.5
    # C3 mid/drop scoring: base - dt * falloff, floored.
    c3_mid_base: float = 0.5
    c3_mid_falloff_per_s: float = 0.014
    c3_mid_floor: float = 0.15
    # C2 scoring: base - dt * falloff, floored, ignoring the first c2_min_dt_s.
    c2_min_dt_s: float = 2.0
    c2_base: float = 0.32
    c2_falloff_per_s: float = 0.003
    c2_floor: float = 0.05
    # Candidates scoring at/above this are pre-selected as the machine's "same
    # piece" prediction (the C3 exit band, by construction of c3_exit_floor).
    predict_threshold: float = 0.5

    @property
    def lookback_window_s(self) -> float:
        # Widest window — bounds the time-range query before per-crop scoring.
        return max(self.c3_lookback_s, self.c2_lookback_s, self.c3_exit_lookback_s)


DEFAULT_PARAMS = ChannelCropLookupParams()


def _atExit(zone: Optional[int], deg: Optional[float], p: ChannelCropLookupParams) -> bool:
    return zone in (p.zone_exit, p.zone_precise) or (deg is not None and abs(deg) < p.exit_deg)


def scoreCrop(crop: dict[str, Any], arrival_ts: float, p: ChannelCropLookupParams = DEFAULT_PARAMS) -> Optional[float]:
    """Confidence that `crop` is the same piece that arrived at `arrival_ts`.

    `crop` needs keys: channel, ts, zone_code, com_forward_to_exit_deg.
    Returns None if the crop is out of window or on an unscored channel.
    """
    ts = crop.get("ts")
    if ts is None:
        return None
    dt = arrival_ts - ts
    if dt < -p.fwd_slop_s:
        return None
    channel = crop.get("channel")
    zone = crop.get("zone_code")
    deg = crop.get("com_forward_to_exit_deg")
    if channel == 3:
        if _atExit(zone, deg, p) and dt <= p.c3_exit_lookback_s:
            return max(p.c3_exit_floor, p.c3_exit_peak - abs(dt - p.peak_dt_s) * p.c3_exit_falloff_per_s)
        if dt <= p.c3_lookback_s:
            return max(p.c3_mid_floor, p.c3_mid_base - dt * p.c3_mid_falloff_per_s)
        return None
    if channel == 2:
        if p.c2_min_dt_s <= dt <= p.c2_lookback_s:
            return max(p.c2_floor, p.c2_base - dt * p.c2_falloff_per_s)
        return None
    return None


def isPredicted(score: Optional[float], p: ChannelCropLookupParams = DEFAULT_PARAMS) -> bool:
    return score is not None and score >= p.predict_threshold
