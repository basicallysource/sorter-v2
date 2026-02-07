import os
from logger import Logger


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        self.main_loop_sleep_ms = 10
        self.heartbeat_interval_ms = 5000


class RotorPulseConfig:
    steps_per_pulse: int
    delay_us: int
    delay_between_pulse_ms: int

    def __init__(self, steps: int, delay_us: int, delay_between_ms: int):
        self.steps_per_pulse = steps
        self.delay_us = delay_us
        self.delay_between_pulse_ms = delay_between_ms


class FeederConfig:
    first_rotor: RotorPulseConfig
    second_rotor: RotorPulseConfig
    third_rotor_normal: RotorPulseConfig
    third_rotor_precision: RotorPulseConfig
    third_channel_dropzone_threshold_px: int
    second_channel_dropzone_threshold_px: int
    object_channel_overlap_threshold: float
    carousel_proximity_threshold_px: int

    def __init__(self):
        self.first_rotor = RotorPulseConfig(
            steps=200, delay_us=200, delay_between_ms=2000
        )
        self.second_rotor = RotorPulseConfig(
            steps=500, delay_us=200, delay_between_ms=250
        )
        self.third_rotor_normal = RotorPulseConfig(
            steps=1000, delay_us=200, delay_between_ms=250
        )
        self.third_rotor_precision = RotorPulseConfig(
            steps=100, delay_us=800, delay_between_ms=350
        )
        self.third_channel_dropzone_threshold_px = 350
        self.second_channel_dropzone_threshold_px = 500
        self.object_channel_overlap_threshold = 0.15
        self.carousel_proximity_threshold_px = 110


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts
    feeder_config: FeederConfig
    classification_chamber_vision_model_path: str
    feeder_vision_model_path: str
    parts_with_categories_file_path: str
    vision_mask_proximity_threshold: float
    should_write_camera_feeds: bool

    def __init__(self):
        self.debug_level = 0
        self.vision_mask_proximity_threshold = 0.5
        self.should_write_camera_feeds = True


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


def mkFeederConfig() -> FeederConfig:
    feeder_config = FeederConfig()
    return feeder_config


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.logger = Logger(gc.debug_level)
    gc.timeouts = mkTimeouts()
    gc.feeder_config = mkFeederConfig()
    gc.classification_chamber_vision_model_path = os.environ[
        "CLASSIFICATION_CHAMBER_MODEL_PATH"
    ]
    gc.feeder_vision_model_path = os.environ["FEEDER_MODEL_PATH"]
    gc.parts_with_categories_file_path = os.environ["PARTS_WITH_CATEGORIES_FILE_PATH"]
    return gc
