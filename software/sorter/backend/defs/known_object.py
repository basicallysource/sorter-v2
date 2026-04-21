from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum
import uuid
import time


class PieceStage(str, Enum):
    created = "created"
    distributing = "distributing"
    distributed = "distributed"


class ClassificationStatus(str, Enum):
    pending = "pending"
    classifying = "classifying"
    classified = "classified"
    unknown = "unknown"
    not_found = "not_found"
    multi_drop_fail = "multi_drop_fail"


@dataclass
class CarouselMotionSample:
    observed_at: float
    piece_angle_deg: float
    carousel_angle_deg: float
    piece_speed_deg_per_s: float
    carousel_speed_deg_per_s: float
    sync_ratio: float


@dataclass
class KnownObject:
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stage: PieceStage = PieceStage.created
    classification_status: ClassificationStatus = ClassificationStatus.pending
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
    thumbnail: Optional[str] = None
    top_image: Optional[str] = None
    bottom_image: Optional[str] = None
    # Full classification chamber (carousel) frame captured at the instant
    # this piece was locked for drop — base64 JPEG, max 1024 px wide so the
    # event payload stays bounded. Used on the detail page to visually verify
    # the classification against the Brickognize reference image.
    drop_snapshot: Optional[str] = None
    brickognize_preview_url: Optional[str] = None
    brickognize_source_view: Optional[str] = None
    # Captured timestamps of the crops actually shipped to Brickognize for
    # classification (subset of the tracker's sector snapshots). The frontend
    # uses these to highlight which crops participated in the final call.
    recognition_used_crop_ts: List[float] = field(default_factory=list)
    tracked_global_id: Optional[int] = None
    classification_channel_size_class: Optional[str] = None
    classification_channel_zone_state: Optional[str] = None
    classification_channel_zone_center_deg: Optional[float] = None
    classification_channel_zone_half_width_deg: Optional[float] = None
    classification_channel_soft_guard_deg: Optional[float] = None
    classification_channel_hard_guard_deg: Optional[float] = None
    carousel_motion_sync_ratio: Optional[float] = None
    carousel_motion_sync_ratio_avg: Optional[float] = None
    carousel_motion_sync_ratio_min: Optional[float] = None
    carousel_motion_sync_ratio_max: Optional[float] = None
    carousel_motion_piece_speed_deg_per_s: Optional[float] = None
    carousel_motion_platter_speed_deg_per_s: Optional[float] = None
    carousel_motion_sample_count: int = 0
    carousel_motion_under_sync_sample_count: int = 0
    carousel_motion_over_sync_sample_count: int = 0
    carousel_motion_samples: List[CarouselMotionSample] = field(default_factory=list)
    feeding_started_at: Optional[float] = None
    carousel_detected_confirmed_at: Optional[float] = None
    first_carousel_seen_ts: Optional[float] = None
    # Polar angle on the carousel (degrees) at the instant the piece was
    # first observed in a carousel-source zone. Used by the classification
    # channel recognizer to gate firing until the piece has traversed a
    # minimum angular distance, guaranteeing viewing-angle diversity for
    # the accumulated crops independent of rotation speed.
    first_carousel_seen_angle_deg: Optional[float] = None
    carousel_rotate_started_at: Optional[float] = None
    carousel_rotated_at: Optional[float] = None
    carousel_snapping_started_at: Optional[float] = None
    carousel_snapping_completed_at: Optional[float] = None
    carousel_next_baseline_captured_at: Optional[float] = None
    carousel_next_ready_at: Optional[float] = None
    classified_at: Optional[float] = None
    distributing_at: Optional[float] = None
    distribution_target_selected_at: Optional[float] = None
    distribution_motion_started_at: Optional[float] = None
    distribution_positioned_at: Optional[float] = None
    distributed_at: Optional[float] = None
    _carousel_motion_last_piece_angle_deg: Optional[float] = None
    _carousel_motion_last_carousel_angle_deg: Optional[float] = None
    _carousel_motion_last_observed_at: Optional[float] = None
    _carousel_motion_piece_delta_sum_deg: float = 0.0
    _carousel_motion_platter_delta_sum_deg: float = 0.0
