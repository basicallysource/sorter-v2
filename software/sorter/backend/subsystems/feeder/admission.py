from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irl.config import ClassificationChannelConfig
    from subsystems.classification_channel.zone_manager import ZoneManager


MAX_CLASSIFICATION_CHANNEL_PIECES = 1
CLASSIFICATION_CHANNEL_ID = 4


def estimate_piece_count_for_channel(
    detections: list,
    *,
    channel_id: int,
    track_count: int,
) -> int:
    detection_count = 0
    for detection in detections:
        if getattr(detection, "channel_id", None) == channel_id:
            detection_count += 1
    return max(int(track_count), detection_count)


def classification_channel_admission_blocked(
    detections: list,
    *,
    track_count: int,
    transport_piece_count: int,
    zone_manager: "ZoneManager | None" = None,
    config: "ClassificationChannelConfig | None" = None,
) -> bool:
    max_zones = (
        max(1, int(config.max_zones))
        if config is not None
        else MAX_CLASSIFICATION_CHANNEL_PIECES
    )
    if zone_manager is not None and config is not None:
        if zone_manager.zone_count() >= max_zones:
            return True
        if not zone_manager.is_arc_clear(
            center_deg=config.intake_angle_deg,
            body_half_width_deg=config.intake_body_half_width_deg,
            hard_guard_deg=config.intake_guard_deg,
        ):
            return True
        # In dynamic-zone mode the classification channel is coordinated via
        # explicit handoff + tracked reservations. Raw detector blobs are too
        # noisy here (e.g. output guide / static geometry) and would block C3
        # even when C4 is physically empty. Once the bus/transport owns the
        # channel state, trust that state instead of fallback detections.
        return int(transport_piece_count) >= max_zones
    vision_piece_count = estimate_piece_count_for_channel(
        detections,
        channel_id=CLASSIFICATION_CHANNEL_ID,
        track_count=track_count,
    )
    return max(vision_piece_count, int(transport_piece_count)) >= max_zones


__all__ = [
    "CLASSIFICATION_CHANNEL_ID",
    "MAX_CLASSIFICATION_CHANNEL_PIECES",
    "classification_channel_admission_blocked",
    "estimate_piece_count_for_channel",
]
