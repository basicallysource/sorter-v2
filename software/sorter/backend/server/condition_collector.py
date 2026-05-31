"""Piece-crop condition collector for Hive.

This module is the sorter-side "just collect" path: when a track finalizes we
pick a couple of in-memory piece crops, quality-gate them, and hand them to
the classification training manager so they ship to Hive as `condition`
samples. Labeling (composition/condition/flags) happens later on Hive.

We do not call any vision LLM here — that was the old `condition_teacher`
loop. Keeping the sorter dumb on this side avoids paid API calls on the hot
path and keeps the runtime classifier-agnostic.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Iterable

import cv2
import numpy as np


CONDITION_SAMPLE_SCHEMA_VERSION = "piece_condition_v1"
CONDITION_SOURCE = "piece_condition_collector_capture"
CONDITION_CAPTURE_REASON = "piece_condition_collector"
CONDITION_STAGE = "part_condition_quality"

MIN_CONDITION_CROP_SIDE_PX = 8
MIN_CONDITION_CROP_MEAN_GRAY = 5.0
MIN_CONDITION_CROP_NONBLACK_RATIO = 0.02
MIN_CONDITION_CROP_P95_GRAY = 24.0
CONDITION_CROP_NONBLACK_THRESHOLD = 12


@dataclass(frozen=True, slots=True)
class ConditionCropPick:
    """One in-memory crop selected for upload as a condition sample."""

    image_bgr: np.ndarray
    width: int
    height: int
    stats: dict[str, float]
    sharpness: float
    snapshot_index: int
    selection: str  # "sharpest" | "diversity"


def _decode_b64_to_bgr(b64: str) -> np.ndarray | None:
    if not isinstance(b64, str) or not b64:
        return None
    try:
        raw = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError):
        return None
    if not raw:
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        return None
    return img


def crop_stats(image_bgr: np.ndarray) -> dict[str, float]:
    """Compact quality + sharpness stats for one decoded crop."""

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {
        "width": float(gray.shape[1]),
        "height": float(gray.shape[0]),
        "mean_gray": float(gray.mean()),
        "nonblack_ratio": float((gray > CONDITION_CROP_NONBLACK_THRESHOLD).mean()),
        "p95_gray": float(np.percentile(gray, 95)),
        "sharpness": sharpness,
    }


def crop_is_usable(stats: dict[str, float]) -> bool:
    return (
        stats.get("width", 0.0) >= MIN_CONDITION_CROP_SIDE_PX
        and stats.get("height", 0.0) >= MIN_CONDITION_CROP_SIDE_PX
        and stats.get("mean_gray", 0.0) >= MIN_CONDITION_CROP_MEAN_GRAY
        and stats.get("nonblack_ratio", 0.0) >= MIN_CONDITION_CROP_NONBLACK_RATIO
        and stats.get("p95_gray", 0.0) >= MIN_CONDITION_CROP_P95_GRAY
    )


def _stats_distance(a: dict[str, float], b: dict[str, float]) -> float:
    """L2 distance in the (mean_gray, nonblack_ratio, sharpness) space.

    Used to pick a second crop that is visually different from the sharpest.
    The three axes are loosely orthogonal: brightness, fill, and focus.
    """

    da = (a.get("mean_gray", 0.0) - b.get("mean_gray", 0.0)) / 255.0
    db = a.get("nonblack_ratio", 0.0) - b.get("nonblack_ratio", 0.0)
    # Sharpness range is wide; normalize by the larger of the two so two
    # tiny variations near zero don't dominate the distance.
    s_max = max(1.0, a.get("sharpness", 0.0), b.get("sharpness", 0.0))
    dc = (a.get("sharpness", 0.0) - b.get("sharpness", 0.0)) / s_max
    return (da * da + db * db + dc * dc) ** 0.5


def select_condition_picks(
    snapshot_jpegs_b64: Iterable[str],
    *,
    max_picks: int = 2,
) -> list[ConditionCropPick]:
    """Pick up to ``max_picks`` quality-gated crops from the track snapshots.

    Strategy: always include the sharpest usable crop first, then fill with
    snapshots that are as different as possible from the sharpest along the
    brightness/fill/sharpness axes. Anything failing the quality gate is
    skipped silently.
    """

    if max_picks <= 0:
        return []

    candidates: list[tuple[int, np.ndarray, dict[str, float]]] = []
    for idx, b64 in enumerate(snapshot_jpegs_b64):
        image = _decode_b64_to_bgr(b64)
        if image is None:
            continue
        stats = crop_stats(image)
        if not crop_is_usable(stats):
            continue
        candidates.append((idx, image, stats))

    if not candidates:
        return []

    candidates.sort(key=lambda item: item[2].get("sharpness", 0.0), reverse=True)
    sharpest_idx, sharpest_img, sharpest_stats = candidates[0]
    picks: list[ConditionCropPick] = [
        ConditionCropPick(
            image_bgr=sharpest_img,
            width=int(sharpest_stats["width"]),
            height=int(sharpest_stats["height"]),
            stats=sharpest_stats,
            sharpness=sharpest_stats.get("sharpness", 0.0),
            snapshot_index=sharpest_idx,
            selection="sharpest",
        )
    ]

    remaining = candidates[1:]
    while remaining and len(picks) < max_picks:
        # Pick the candidate farthest from the sharpest in stats space.
        remaining.sort(
            key=lambda item: _stats_distance(item[2], sharpest_stats),
            reverse=True,
        )
        chosen_idx, chosen_img, chosen_stats = remaining.pop(0)
        picks.append(
            ConditionCropPick(
                image_bgr=chosen_img,
                width=int(chosen_stats["width"]),
                height=int(chosen_stats["height"]),
                stats=chosen_stats,
                sharpness=chosen_stats.get("sharpness", 0.0),
                snapshot_index=chosen_idx,
                selection="diversity",
            )
        )
    return picks


def build_condition_metadata(
    *,
    pick: ConditionCropPick,
    piece_global_id: int,
    source_role: str,
    track_first_seen_ts: float,
    track_last_seen_ts: float,
    sector_snapshots_total: int,
    handoff_from: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape the metadata block that flags a sample as a condition crop."""

    base: dict[str, Any] = {
        "condition_sample": True,
        "condition_source": "track_finalize_inline",
        "condition_source_track_global_id": int(piece_global_id),
        "condition_source_role": source_role,
        "condition_source_handoff_from": handoff_from,
        "condition_source_track_first_seen_ts": float(track_first_seen_ts),
        "condition_source_track_last_seen_ts": float(track_last_seen_ts),
        "condition_source_snapshot_index": int(pick.snapshot_index),
        "condition_source_snapshot_count": int(sector_snapshots_total),
        "condition_source_selection": pick.selection,
        "condition_source_crop_stats": pick.stats,
        "condition_source_crop_sharpness": float(pick.sharpness),
        "condition_schema_version": CONDITION_SAMPLE_SCHEMA_VERSION,
    }
    if extra:
        base.update(extra)
    return base
