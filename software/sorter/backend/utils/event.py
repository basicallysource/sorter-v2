from defs.known_object import KnownObject
from defs.events import (
    KnownObjectEvent,
    KnownObjectData,
    PieceStage,
    ClassificationStatus,
)


def knownObjectToEvent(obj: KnownObject) -> KnownObjectEvent:
    return KnownObjectEvent(
        tag="known_object",
        data=KnownObjectData(
            uuid=obj.uuid,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            stage=PieceStage(obj.stage),
            classification_status=ClassificationStatus(obj.classification_status),
            part_id=obj.part_id,
            color_id=obj.color_id,
            color_name=obj.color_name,
            category_id=obj.category_id,
            confidence=obj.confidence,
            destination_bin=obj.destination_bin,
            thumbnail=obj.thumbnail,
            top_image=obj.top_image,
            bottom_image=obj.bottom_image,
            brickognize_preview_url=obj.brickognize_preview_url,
            brickognize_source_view=obj.brickognize_source_view,
            feeding_started_at=obj.feeding_started_at,
            carousel_detected_confirmed_at=obj.carousel_detected_confirmed_at,
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
