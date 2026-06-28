from enum import Enum


class ClassificationChannelState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DETECTING = "detecting"
    SNAPPING = "snapping"
    EJECTING = "ejecting"
    # Rev01 simple-state-machine states (reverse-direction, capture-at-rest flow):
    #   CAPTURING (photograph at rest, spawn classify) -> MOVING_TO_PRECISE
    #   (reverse-converge to the precise zone while classify runs) ->
    #   AWAITING_DISTRIBUTION (apply result, hand to distribution, wait for the
    #   chute) -> DISCHARGING (reverse-converge into the fall-off and eject).
    REV01_CAPTURING = "rev01_capturing"
    REV01_MOVING_TO_PRECISE = "rev01_moving_to_precise"
    REV01_AWAITING_DISTRIBUTION = "rev01_awaiting_distribution"
    REV01_DISCHARGING = "rev01_discharging"
    # Deprecated. Kept only so any persisted/serialized value still deserializes:
    # REV01_ROTATING_AND_CAPTURING/CLASSIFYING/POSITIONING were the forward-sweep
    # flow superseded by the states above; VERIFYING_DISCHARGE folded into
    # REV01_DISCHARGING's closed-loop discharge. None are in the live state map.
    REV01_ROTATING_AND_CAPTURING = "rev01_rotating_and_capturing"
    REV01_CLASSIFYING = "rev01_classifying"
    REV01_POSITIONING = "rev01_positioning"
    REV01_VERIFYING_DISCHARGE = "rev01_verifying_discharge"
