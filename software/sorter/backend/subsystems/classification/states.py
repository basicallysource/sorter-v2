from enum import Enum


class ClassificationState(Enum):
    IDLE = "idle"
    DETECTING = "detecting"
    ROTATING = "rotating"
    SNAPPING = "snapping"
