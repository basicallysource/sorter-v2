from typing import Any

from defs.known_object import KnownObject
from defs.events import (
    ClassificationAttempt,
    ClassificationAttemptStrategy,
    KnownObjectEvent,
    KnownObjectData,
    PieceStage,
    ClassificationStatus,
    RecognitionImage,
)


# Heavy, write-once KnownObject fields that exist for server-side lookup only
# and must NOT travel over the live control socket. They are kept in the
# in-memory lookup (runtime_stats) and served on demand by the per-piece detail
# page via /api/known-objects/<uuid>. recognition_image_set in particular is a
# list that grows one base64 crop per capture; re-broadcasting the whole list on every
# capture made known_object payloads grow quadratically and backed up the socket
# broadcaster. The live UI renders latest_captured_crop (bounded), not this list.
# Add a field here to drop it from the live socket without touching call sites.
KNOWN_OBJECT_LOOKUP_ONLY_FIELDS = frozenset({"recognition_image_set"})


def slimKnownObjectForSocket(data: dict[str, Any]) -> dict[str, Any]:
    """Single boundary for what a known_object carries over the live socket.

    Returns a copy of the known_object ``data`` dict with the lookup-only
    (heavy) fields removed. Used by both the live broadcaster and the WS replay
    so the rule lives in exactly one place.
    """
    return {
        key: value
        for key, value in data.items()
        if key not in KNOWN_OBJECT_LOOKUP_ONLY_FIELDS
    }


def knownObjectToEvent(obj: KnownObject) -> KnownObjectEvent:
    return KnownObjectEvent(
        tag="known_object",
        data=KnownObjectData(
            uuid=obj.uuid,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            stage=PieceStage(obj.stage),
            classification_status=ClassificationStatus(obj.classification_status),
            request_failed=obj.request_failed,
            aborted=obj.aborted,
            dead=obj.dead,
            part_id=obj.part_id,
            part_name=obj.part_name,
            part_category=obj.part_category,
            color_id=obj.color_id,
            color_name=obj.color_name,
            category_id=obj.category_id,
            confidence=obj.confidence,
            max_dimension_mm=obj.max_dimension_mm,
            moving_avg_price=obj.moving_avg_price,
            piece_metadata=obj.piece_metadata,
            high_value_routed=obj.high_value_routed,
            not_in_inventory=obj.not_in_inventory,
            too_big=obj.too_big,
            too_big_for_layer=obj.too_big_for_layer,
            intended_layer_index=obj.intended_layer_index,
            destination_bin=obj.destination_bin,
            tracked_global_id=obj.tracked_global_id,
            classification_channel_zone_state=obj.classification_channel_zone_state,
            classification_channel_zone_center_deg=obj.classification_channel_zone_center_deg,
            classification_channel_zone_half_width_deg=obj.classification_channel_zone_half_width_deg,
            classification_channel_exit_offset_deg=obj.classification_channel_exit_offset_deg,
            first_carousel_seen_angle_deg=obj.first_carousel_seen_angle_deg,
            thumbnail=obj.thumbnail,
            latest_captured_crop=obj.latest_captured_crop,
            latest_captured_crop_ts=obj.latest_captured_crop_ts,
            top_image=obj.top_image,
            bottom_image=obj.bottom_image,
            drop_snapshot=obj.drop_snapshot,
            brickognize_preview_url=obj.brickognize_preview_url,
            brickognize_source_view=obj.brickognize_source_view,
            recognition_used_crop_ts=list(obj.recognition_used_crop_ts or []),
            recognition_image_set=[
                RecognitionImage(
                    image=r.image,
                    source=r.source,
                    used=r.used,
                    ts=r.ts,
                    score=r.score,
                    channel=r.channel,
                    created_at=getattr(r, "created_at", None),
                    excluded_from_result=getattr(r, "excluded_from_result", False),
                    sharpness=getattr(r, "sharpness", None),
                )
                for r in (obj.recognition_image_set or [])
            ],
            classification_attempts=[
                ClassificationAttempt(
                    strategy=ClassificationAttemptStrategy(a.strategy),
                    n_burst=a.n_burst,
                    n_upstream=a.n_upstream,
                    found=a.found,
                    label=a.label,
                    applied=a.applied,
                    part_id=a.part_id,
                    part_name=a.part_name,
                    preview_url=a.preview_url,
                    confidence=a.confidence,
                    color_id=a.color_id,
                    color_name=a.color_name,
                    error=a.error,
                    duration_s=a.duration_s,
                    image_ts=list(a.image_ts or []),
                )
                for a in (obj.classification_attempts or [])
            ],
            classification_strategy=(
                ClassificationAttemptStrategy(obj.classification_strategy)
                if obj.classification_strategy is not None
                else None
            ),
            feeding_started_at=obj.feeding_started_at,
            carousel_detected_confirmed_at=obj.carousel_detected_confirmed_at,
            first_carousel_seen_ts=obj.first_carousel_seen_ts,
            carousel_rotate_started_at=obj.carousel_rotate_started_at,
            carousel_rotated_at=obj.carousel_rotated_at,
            carousel_snapping_started_at=obj.carousel_snapping_started_at,
            carousel_snapping_completed_at=obj.carousel_snapping_completed_at,
            carousel_next_baseline_captured_at=obj.carousel_next_baseline_captured_at,
            carousel_next_ready_at=obj.carousel_next_ready_at,
            classified_at=obj.classified_at,
            distributing_at=obj.distributing_at,
            distribution_target_selected_at=obj.distribution_target_selected_at,
            distribution_motion_started_at=obj.distribution_motion_started_at,
            distribution_positioned_at=obj.distribution_positioned_at,
            distributed_at=obj.distributed_at,
        ),
    )
