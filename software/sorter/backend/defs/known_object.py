from dataclasses import dataclass, field
from typing import Optional, Tuple
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
class KnownObject:
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stage: PieceStage = PieceStage.created
    classification_status: ClassificationStatus = ClassificationStatus.pending
    part_id: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
    tracked_global_id: Optional[int] = None
    thumbnail: Optional[str] = None
    top_image: Optional[str] = None
    bottom_image: Optional[str] = None
    brickognize_preview_url: Optional[str] = None
    brickognize_source_view: Optional[str] = None
    feeding_started_at: Optional[float] = None
    carousel_detected_confirmed_at: Optional[float] = None
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
