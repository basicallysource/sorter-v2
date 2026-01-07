from pydantic import BaseModel
from typing import Literal, Union


class HeartbeatData(BaseModel):
    timestamp: float


class HeartbeatEvent(BaseModel):
    tag: Literal["heartbeat"]
    data: HeartbeatData


SocketEvent = Union[HeartbeatEvent]
MainThreadToServerCommand = Union[HeartbeatEvent]
ServerToMainThreadEvent = Union[HeartbeatEvent]
