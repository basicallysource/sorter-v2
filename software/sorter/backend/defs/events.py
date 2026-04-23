from pydantic import BaseModel, Field
from typing import Literal, Union, Optional, Tuple, List
from enum import Enum


class CameraName(str, Enum):
    feeder = "feeder"
    classification_bottom = "classification_bottom"
    classification_top = "classification_top"
    c_channel_2 = "c_channel_2"
    c_channel_3 = "c_channel_3"
    carousel = "carousel"
    classification_channel = "classification_channel"


class PieceStage(str, Enum):
    created = "created"
    registered = "registered"
    classified = "classified"
    distributing = "distributing"
    distributed = "distributed"


class ClassificationStatus(str, Enum):
    pending = "pending"
    classifying = "classifying"
    classified = "classified"
    unknown = "unknown"
    not_found = "not_found"
    multi_drop_fail = "multi_drop_fail"


class HeartbeatData(BaseModel):
    timestamp: float


class HeartbeatEvent(BaseModel):
    tag: Literal["heartbeat"]
    data: HeartbeatData


class FrameResultData(BaseModel):
    class_id: Optional[int]
    class_name: Optional[str]
    confidence: float
    bbox: Optional[Tuple[int, int, int, int]]


class RingGeom(BaseModel):
    """Per-camera ring geometry in source-frame pixel coords.

    Attached to every FrameData when the camera is an arc channel so the
    client can render wedge overlays without re-reading the saved polygon
    blob.
    """
    center_x: float
    center_y: float
    inner_radius: float
    outer_radius: float


class SlotWedge(BaseModel):
    """Occupied angular slot on the camera's ring — dossier zone for C4,
    confirmed-real piece position for C2/C3."""
    start_angle_deg: float
    end_angle_deg: float
    label: Optional[str] = None
    color: Optional[str] = None


class FrameData(BaseModel):
    camera: CameraName
    timestamp: float
    raw: str
    annotated: Optional[str]
    results: List[FrameResultData]
    # Ghost-marked track bboxes (x1, y1, x2, y2) in source-frame coords.
    # Rendered client-side as a separate toggleable SVG overlay so operators
    # can flip their visibility without a server round-trip.
    ghost_boxes: List[Tuple[int, int, int, int]] = []
    # Ring geometry + per-piece slot wedges for the runtime "slots" overlay.
    # ``ring_geom`` is None for cameras that don't live on an arc channel.
    ring_geom: Optional[RingGeom] = None
    slot_wedges: List[SlotWedge] = []


class FrameEvent(BaseModel):
    tag: Literal["frame"]
    data: FrameData


class MachineIdentityData(BaseModel):
    machine_id: str
    nickname: Optional[str]


class IdentityEvent(BaseModel):
    tag: Literal["identity"]
    data: MachineIdentityData


class CarouselMotionSampleData(BaseModel):
    observed_at: float
    piece_angle_deg: float
    carousel_angle_deg: float
    piece_speed_deg_per_s: float
    carousel_speed_deg_per_s: float
    sync_ratio: float


class KnownObjectData(BaseModel):
    uuid: str
    created_at: float
    updated_at: float
    stage: PieceStage
    classification_status: ClassificationStatus
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
    tracked_global_id: Optional[int] = None
    thumbnail: Optional[str] = None
    top_image: Optional[str] = None
    bottom_image: Optional[str] = None
    preview_jpeg_path: Optional[str] = None
    drop_snapshot: Optional[str] = None
    brickognize_preview_url: Optional[str] = None
    brickognize_source_view: Optional[str] = None
    bin_id: Optional[str] = None
    distribution_reason: Optional[str] = None
    # Captured timestamps of crops shipped to Brickognize for this piece.
    recognition_used_crop_ts: List[float] = Field(default_factory=list)
    feeding_started_at: Optional[float] = None
    carousel_detected_confirmed_at: Optional[float] = None
    first_carousel_seen_ts: Optional[float] = None
    first_carousel_seen_angle_deg: Optional[float] = None
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
    carousel_motion_samples: List[CarouselMotionSampleData] = Field(default_factory=list)
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


class KnownObjectEvent(BaseModel):
    tag: Literal["known_object"]
    data: KnownObjectData


class CameraHealthData(BaseModel):
    cameras: dict[str, str]  # role → "online"|"offline"|"reconnecting"|"unassigned"


class CameraHealthEvent(BaseModel):
    tag: Literal["camera_health"]
    data: CameraHealthData


class SystemStatusData(BaseModel):
    hardware_state: str
    hardware_error: Optional[str] = None
    homing_step: Optional[str] = None


class SystemStatusEvent(BaseModel):
    tag: Literal["system_status"]
    data: SystemStatusData


class SorterStateData(BaseModel):
    state: str
    camera_layout: Optional[str] = None


class SorterStateEvent(BaseModel):
    tag: Literal["sorter_state"]
    data: SorterStateData


class CamerasConfigData(BaseModel):
    cameras: dict[str, Union[int, str, None]]


class CamerasConfigEvent(BaseModel):
    tag: Literal["cameras_config"]
    data: CamerasConfigData


class SortingProfileStatusData(BaseModel):
    sync_state: dict
    local_profile: dict


class SortingProfileStatusEvent(BaseModel):
    tag: Literal["sorting_profile_status"]
    data: SortingProfileStatusData


class RuntimeStatsData(BaseModel):
    payload: dict


class RuntimeStatsEvent(BaseModel):
    tag: Literal["runtime_stats"]
    data: RuntimeStatsData


class PauseCommandData(BaseModel):
    pass


class PauseCommandEvent(BaseModel):
    tag: Literal["pause"]
    data: PauseCommandData


class ResumeCommandData(BaseModel):
    pass


class ResumeCommandEvent(BaseModel):
    tag: Literal["resume"]
    data: ResumeCommandData


SocketEvent = Union[
    HeartbeatEvent,
    FrameEvent,
    IdentityEvent,
    KnownObjectEvent,
    CameraHealthEvent,
    SystemStatusEvent,
    SorterStateEvent,
    CamerasConfigEvent,
    SortingProfileStatusEvent,
    RuntimeStatsEvent,
]
MainThreadToServerCommand = Union[
    HeartbeatEvent,
    FrameEvent,
    KnownObjectEvent,
    CameraHealthEvent,
    SystemStatusEvent,
    SorterStateEvent,
    CamerasConfigEvent,
    SortingProfileStatusEvent,
    RuntimeStatsEvent,
]
ServerToMainThreadEvent = Union[HeartbeatEvent, PauseCommandEvent, ResumeCommandEvent]
