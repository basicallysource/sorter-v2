from enum import Enum


class ClassificationChannelState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DETECTING = "detecting"
    SNAPPING = "snapping"
    EJECTING = "ejecting"
    # Rev01 simple-state-machine states
    REV01_ROTATING_AND_CAPTURING = "rev01_rotating_and_capturing"
    REV01_CLASSIFYING = "rev01_classifying"
    REV01_DISCHARGING = "rev01_discharging"
