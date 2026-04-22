from enum import Enum


class ClassificationChannelState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DETECTING = "detecting"
    SNAPPING = "snapping"
    EJECTING = "ejecting"
