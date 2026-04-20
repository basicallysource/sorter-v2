from __future__ import annotations


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
) -> bool:
    vision_piece_count = estimate_piece_count_for_channel(
        detections,
        channel_id=CLASSIFICATION_CHANNEL_ID,
        track_count=track_count,
    )
    return max(vision_piece_count, int(transport_piece_count)) >= MAX_CLASSIFICATION_CHANNEL_PIECES


__all__ = [
    "CLASSIFICATION_CHANNEL_ID",
    "MAX_CLASSIFICATION_CHANNEL_PIECES",
    "classification_channel_admission_blocked",
    "estimate_piece_count_for_channel",
]
