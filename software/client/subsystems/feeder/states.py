from enum import Enum


OBJECT_CLASS_ID = 0
CAROUSEL_CLASS_ID = 1
THIRD_V_CHANNEL_CLASS_ID = 2
SECOND_V_CHANNEL_CLASS_ID = 3
FIRST_V_CHANNEL_CLASS_ID = 4


class FeederState(Enum):
    IDLE = "idle"
    FEEDING = "feeding"
    V3_DISPENSING = "v3_dispensing"
    V3_DISPENSING_SLOW = "v3_dispensing_slow"
    V2_LOADING = "v2_loading"
    V1_LOADING = "v1_loading"
