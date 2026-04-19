from enum import Enum


class ClassificationChannelState(str, Enum):
    IDLE = "idle"
    DETECTING = "detecting"
    SNAPPING = "snapping"
    EJECTING = "ejecting"
