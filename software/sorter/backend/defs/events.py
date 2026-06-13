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


class FrameData(BaseModel):
    camera: CameraName
    timestamp: float
    raw: str
    annotated: Optional[str]
    results: List[FrameResultData]


class FrameEvent(BaseModel):
    tag: Literal["frame"]
    data: FrameData


class MachineIdentityData(BaseModel):
    machine_id: str
    nickname: Optional[str]


class IdentityEvent(BaseModel):
    tag: Literal["identity"]
    data: MachineIdentityData


class RecognitionImage(BaseModel):
    image: str
    source: str
    used: bool = False
    ts: Optional[float] = None
    score: Optional[float] = None
    # True when this image was submitted in an earlier classification attempt
    # that recognized nothing and was then removed for the retry whose result
    # was applied (distinct from used=False, which means "never sent").
    excluded_from_result: bool = False


class ClassificationAttemptStrategy(str, Enum):
    initial = "initial"
    drop_upstream = "drop_upstream"
    split_singles = "split_singles"


class ClassificationAttempt(BaseModel):
    strategy: ClassificationAttemptStrategy
    n_burst: int
    n_upstream: int
    found: bool
    label: Optional[str] = None
    applied: bool = False
    part_id: Optional[str] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None


class KnownObjectData(BaseModel):
    uuid: str
    created_at: float
    updated_at: float
    stage: PieceStage
    classification_status: ClassificationStatus
    aborted: bool = False
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    max_dimension_mm: Optional[float] = None
    too_big: bool = False
    too_big_for_layer: bool = False
    intended_layer_index: Optional[int] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
    tracked_global_id: Optional[int] = None
    classification_channel_zone_state: Optional[str] = None
    classification_channel_zone_center_deg: Optional[float] = None
    classification_channel_zone_half_width_deg: Optional[float] = None
    classification_channel_exit_offset_deg: Optional[float] = None
    first_carousel_seen_angle_deg: Optional[float] = None
    thumbnail: Optional[str] = None
    latest_captured_crop: Optional[str] = None
    latest_captured_crop_ts: Optional[float] = None
    top_image: Optional[str] = None
    bottom_image: Optional[str] = None
    drop_snapshot: Optional[str] = None
    brickognize_preview_url: Optional[str] = None
    brickognize_source_view: Optional[str] = None
    # C4 burst captures + any upstream (C2/C3) match crops, each flagged with
    # whether it was actually submitted to Brickognize.
    recognition_image_set: List["RecognitionImage"] = Field(default_factory=list)
    # Per-attempt Brickognize record; >1 entry means a retry with a reduced image
    # set was made after a no-recognition result. The last entry is the applied
    # one. ``classification_strategy`` is its strategy (``initial`` = first try
    # won; ``drop_upstream`` = won only after dropping the upstream crops).
    classification_attempts: List["ClassificationAttempt"] = Field(default_factory=list)
    classification_strategy: Optional[ClassificationAttemptStrategy] = None
    # Captured timestamps of crops shipped to Brickognize for this piece.
    recognition_used_crop_ts: List[float] = Field(default_factory=list)
    feeding_started_at: Optional[float] = None
    carousel_detected_confirmed_at: Optional[float] = None
    first_carousel_seen_ts: Optional[float] = None
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
    no_power_development_mode: bool = False


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


class SetProfilerEnabledData(BaseModel):
    enabled: bool


class SetProfilerEnabledEvent(BaseModel):
    tag: Literal["set_profiler_enabled"]
    data: SetProfilerEnabledData


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
ServerToMainThreadEvent = Union[
    HeartbeatEvent, PauseCommandEvent, ResumeCommandEvent, SetProfilerEnabledEvent
]
