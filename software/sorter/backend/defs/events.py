from pydantic import BaseModel, Field
from typing import Any, Dict, Literal, Union, Optional, Tuple, List
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
    failed = "failed"


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
    # True when this image was submitted in a parallel classification request
    # that lost (a different request scored higher) and was thrown out (distinct
    # from used=False, which means "never sent").
    excluded_from_result: bool = False
    # Physical channel: 4 for a C4 burst capture, 2 or 3 for an upstream match
    # crop. None when unknown (older records).
    channel: Optional[int] = None
    # Wall-clock capture time (epoch seconds). The UI ages each pic against the
    # owning KnownObject.created_at. None for older records.
    created_at: Optional[float] = None
    # Motion-blur / focus measure: variance of the image's Laplacian (higher =
    # sharper). Set for C4 burst crops at capture; None for upstream crops and
    # older records. Lets consumers judge image validity without redecoding.
    sharpness: Optional[float] = None


class ClassificationAttemptStrategy(str, Enum):
    combined = "combined"
    single_burst = "single_burst"
    single_upstream = "single_upstream"


class ClassificationAttempt(BaseModel):
    strategy: ClassificationAttemptStrategy
    n_burst: int
    n_upstream: int
    found: bool
    label: Optional[str] = None
    applied: bool = False
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    preview_url: Optional[str] = None
    confidence: Optional[float] = None
    color_id: Optional[str] = None
    color_name: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None
    image_ts: List[float] = Field(default_factory=list)


class KnownObjectData(BaseModel):
    uuid: str
    created_at: float
    updated_at: float
    stage: PieceStage
    classification_status: ClassificationStatus
    # True when the Brickognize request failed (timeout/DNS/connection) rather than
    # succeeding with no match. Drives the "Request failed" card label.
    request_failed: bool = False
    aborted: bool = False
    # Set when the backend reaps a piece that went silent for too long without
    # reaching the distributed stage (the time-based analogue of ``aborted``).
    # The UI drops dead pieces from the recent list.
    dead: bool = False
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    max_dimension_mm: Optional[float] = None
    # Headline BrickLink moving-average price (USD) from the local parts.db, plus
    # the full local-DB metadata blob. moving_avg_price is what the Recent Pieces
    # card renders; piece_metadata carries the rest for the detail view.
    moving_avg_price: Optional[float] = None
    piece_metadata: Optional[Dict[str, Any]] = None
    # True when the profile's high_value_routing override rerouted this piece into
    # the high-value category's bin. Drives the "High value" chip on the card.
    high_value_routed: bool = False
    # Live .bsx inventory membership: None = no active inventory; True = stocked;
    # False = not in inventory. Drives the "Not in inventory" badge on the card.
    not_in_inventory: Optional[bool] = None
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
    # Correction provenance from the applied request. brickognize_listing_id being
    # set is what makes a piece "correctable" in the UI (the client can only submit
    # a correction when we captured the listing). Carried on the live payload so a
    # freshly classified piece is correctable immediately, before it's recorded.
    brickognize_listing_id: Optional[str] = None
    brickognize_item_rank: Optional[int] = None
    brickognize_item_type: Optional[str] = None
    brickognize_color_rank: Optional[int] = None
    # C4 burst captures + any upstream (C2/C3) match crops, each flagged with
    # whether it was actually submitted to Brickognize.
    recognition_image_set: List["RecognitionImage"] = Field(default_factory=list)
    # Per-request Brickognize record; the requests fan out in parallel (combined +
    # single-image calls), not as retries. The applied one is flagged.
    # ``classification_strategy`` is which request won (``combined`` = the fused
    # set; ``single_burst`` / ``single_upstream`` = a lone image beat it).
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
