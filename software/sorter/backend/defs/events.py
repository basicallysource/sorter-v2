from pydantic import BaseModel
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


class KnownObjectData(BaseModel):
    uuid: str
    created_at: float
    updated_at: float
    stage: PieceStage
    classification_status: ClassificationStatus
    part_id: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
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


class KnownObjectEvent(BaseModel):
    tag: Literal["known_object"]
    data: KnownObjectData


class CameraHealthData(BaseModel):
    cameras: dict[str, str]  # role → "online"|"offline"|"reconnecting"|"unassigned"


class CameraHealthEvent(BaseModel):
    tag: Literal["camera_health"]
    data: CameraHealthData


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


SocketEvent = Union[HeartbeatEvent, FrameEvent, IdentityEvent, KnownObjectEvent, CameraHealthEvent, RuntimeStatsEvent]
MainThreadToServerCommand = Union[HeartbeatEvent, FrameEvent, KnownObjectEvent, CameraHealthEvent, RuntimeStatsEvent]
ServerToMainThreadEvent = Union[HeartbeatEvent, PauseCommandEvent, ResumeCommandEvent]
