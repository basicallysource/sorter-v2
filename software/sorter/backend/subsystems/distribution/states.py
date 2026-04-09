from enum import Enum


class DistributionState(Enum):
    IDLE = "idle"
    POSITIONING = "positioning"
    READY = "ready"
    SENDING = "sending"
