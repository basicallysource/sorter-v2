from pydantic import BaseModel
from typing import Literal, Union


class MachineStartedData(BaseModel):
    timestamp: float


class MachineStartedEvent(BaseModel):
    tag: Literal["machine_started"]
    data: MachineStartedData


SocketEvent = Union[MachineStartedEvent]
MainThreadToServerCommand = Union[MachineStartedEvent]
ServerToMainThreadEvent = Union[MachineStartedEvent]
