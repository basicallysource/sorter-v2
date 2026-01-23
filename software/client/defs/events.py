from pydantic import BaseModel
from typing import Literal, Union, Optional, Tuple, List
from enum import Enum


class CameraName(str, Enum):
    feeder = "feeder"
    classification_bottom = "classification_bottom"
    classification_top = "classification_top"


class KnownObjectStatus(str, Enum):
    created = "created"
    classifying = "classifying"
    classified = "classified"
    unknown = "unknown"
    not_found = "not_found"
    distributing = "distributing"
    distributed = "distributed"


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
    result: Optional[FrameResultData]


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
    status: KnownObjectStatus
    part_id: Optional[str] = None
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
    thumbnail: Optional[str] = None
    top_image: Optional[str] = None
    bottom_image: Optional[str] = None


class KnownObjectEvent(BaseModel):
    tag: Literal["known_object"]
    data: KnownObjectData


class BinData(BaseModel):
    size: str
    category_id: Optional[str] = None


class LayerData(BaseModel):
    sections: List[List[BinData]]


class DistributionLayoutData(BaseModel):
    layers: List[LayerData]


class DistributionLayoutEvent(BaseModel):
    tag: Literal["distribution_layout"]
    data: DistributionLayoutData


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
    HeartbeatEvent, FrameEvent, IdentityEvent, KnownObjectEvent, DistributionLayoutEvent
]
MainThreadToServerCommand = Union[
    HeartbeatEvent, FrameEvent, KnownObjectEvent, DistributionLayoutEvent
]
ServerToMainThreadEvent = Union[HeartbeatEvent, PauseCommandEvent, ResumeCommandEvent]
