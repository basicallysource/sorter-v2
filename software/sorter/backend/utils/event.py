from defs.known_object import KnownObject
from defs.events import (
    CarouselMotionSampleData,
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
            part_name=obj.part_name,
            part_category=obj.part_category,
            color_id=obj.color_id,
            color_name=obj.color_name,
            category_id=obj.category_id,
            confidence=obj.confidence,
            destination_bin=obj.destination_bin,
            tracked_global_id=obj.tracked_global_id,
            thumbnail=obj.thumbnail,
            top_image=obj.top_image,
            bottom_image=obj.bottom_image,
            drop_snapshot=obj.drop_snapshot,
            brickognize_preview_url=obj.brickognize_preview_url,
            brickognize_source_view=obj.brickognize_source_view,
            recognition_used_crop_ts=list(obj.recognition_used_crop_ts or []),
            feeding_started_at=obj.feeding_started_at,
            carousel_detected_confirmed_at=obj.carousel_detected_confirmed_at,
            first_carousel_seen_ts=obj.first_carousel_seen_ts,
            first_carousel_seen_angle_deg=obj.first_carousel_seen_angle_deg,
            classification_channel_size_class=obj.classification_channel_size_class,
            classification_channel_zone_state=obj.classification_channel_zone_state,
            classification_channel_zone_center_deg=obj.classification_channel_zone_center_deg,
            classification_channel_exit_deg=obj.classification_channel_exit_deg,
            classification_channel_zone_half_width_deg=obj.classification_channel_zone_half_width_deg,
            classification_channel_soft_guard_deg=obj.classification_channel_soft_guard_deg,
            classification_channel_hard_guard_deg=obj.classification_channel_hard_guard_deg,
            carousel_motion_sync_ratio=obj.carousel_motion_sync_ratio,
            carousel_motion_sync_ratio_avg=obj.carousel_motion_sync_ratio_avg,
            carousel_motion_sync_ratio_min=obj.carousel_motion_sync_ratio_min,
            carousel_motion_sync_ratio_max=obj.carousel_motion_sync_ratio_max,
            carousel_motion_piece_speed_deg_per_s=obj.carousel_motion_piece_speed_deg_per_s,
            carousel_motion_platter_speed_deg_per_s=obj.carousel_motion_platter_speed_deg_per_s,
            carousel_motion_sample_count=int(obj.carousel_motion_sample_count or 0),
            carousel_motion_under_sync_sample_count=int(
                obj.carousel_motion_under_sync_sample_count or 0
            ),
            carousel_motion_over_sync_sample_count=int(
                obj.carousel_motion_over_sync_sample_count or 0
            ),
            carousel_motion_samples=[
                CarouselMotionSampleData(
                    observed_at=float(sample.observed_at),
                    piece_angle_deg=float(sample.piece_angle_deg),
                    carousel_angle_deg=float(sample.carousel_angle_deg),
                    piece_speed_deg_per_s=float(sample.piece_speed_deg_per_s),
                    carousel_speed_deg_per_s=float(sample.carousel_speed_deg_per_s),
                    sync_ratio=float(sample.sync_ratio),
                )
                for sample in list(obj.carousel_motion_samples or [])
            ],
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
