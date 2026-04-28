from __future__ import annotations

import math
from typing import Any

from rt.contracts.tracking import Track


class C4ExitGeometry:
    """Pick C4 exit tracks and guard against double-drop geometry."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def has_trailing_piece_within_safety(
        self, matched_track: Track, tracks: list[Track]
    ) -> bool:
        rt = self._rt
        if rt._exit_trailing_safety_deg <= 0.0:
            return False
        matched_uuid = rt._piece_uuid_for_track(matched_track)
        if matched_uuid is None:
            return False
        drop_deg = float(rt._zone_manager.drop_angle_deg)
        for track in tracks:
            if track.angle_rad is None or track.global_id is None:
                continue
            if track is matched_track:
                continue
            other_uuid = rt._piece_uuid_for_track(track)
            if other_uuid is None or other_uuid == matched_uuid:
                continue
            other_angle = math.degrees(track.angle_rad)
            distance_to_chute = abs(_wrap_deg(other_angle - drop_deg))
            if distance_to_chute <= rt._exit_trailing_safety_deg:
                return True
        return False

    def pick_exit_track(self, tracks: list[Track]) -> Track | None:
        rt = self._rt
        best: Track | None = None
        best_score: tuple[float, float] | None = None
        for track in tracks:
            if track.angle_rad is None or track.global_id is None:
                continue
            if rt._piece_uuid_for_track(track) is None:
                continue
            delta = abs(_wrap_deg(math.degrees(track.angle_rad) - rt._exit_angle_deg))
            overlap = rt._exit_zone_bbox_overlap_ratio(track)
            ready = (
                delta <= rt._angle_tol_deg
                if overlap is None
                else overlap >= rt._exit_bbox_overlap_ratio
            )
            if not ready:
                continue
            score = (overlap if overlap is not None else 1.0, -delta)
            if best_score is None or score > best_score:
                best = track
                best_score = score
        return best


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


__all__ = ["C4ExitGeometry"]
