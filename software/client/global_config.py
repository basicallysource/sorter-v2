import os
from logger import Logger


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        self.main_loop_sleep_ms = 10
        self.heartbeat_interval_ms = 5000


class DefaultMotorSpeeds:
    first_v_channel: int
    second_v_channel: int
    third_v_channel: int

    def __init__(self):
        self.first_v_channel = 100
        self.second_v_channel = 100
        self.third_v_channel = 100


class FeederConfig:
    pause_ms: float
    v1_pulse_length_ms: float
    v1_pulse_speed: int
    v2_pulse_length_ms: float
    v2_pulse_speed: int
    v3_pulse_length_ms: float
    v3_pulse_speed: int
    slow_v3_pulse_length_ms: float
    slow_v3_pulse_speed: int
    proximity_threshold_px: int
    proximity_to_carousel_threshold_px: int

    def __init__(self):
        self.pause_ms = 200
        self.v1_pulse_length_ms = 100
        self.v1_pulse_speed = 32
        self.v2_pulse_length_ms = 300
        self.v2_pulse_speed = 30
        self.v3_pulse_length_ms = 300
        self.v3_pulse_speed = 30
        self.slow_v3_pulse_length_ms = 300
        self.slow_v3_pulse_speed = 20
        self.proximity_threshold_px = 40
        self.proximity_to_carousel_threshold_px = 20


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts
    default_motor_speeds: DefaultMotorSpeeds
    feeder_config: FeederConfig
    classification_chamber_vision_model_path: str
    feeder_vision_model_path: str
    vision_mask_proximity_threshold: float
    should_write_camera_feeds: bool

    def __init__(self):
        self.debug_level = 0
        self.vision_mask_proximity_threshold = 0.5
        self.should_write_camera_feeds = True


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


def mkDefaultMotorSpeeds() -> DefaultMotorSpeeds:
    motor_speeds = DefaultMotorSpeeds()
    return motor_speeds


def mkFeederConfig() -> FeederConfig:
    feeder_config = FeederConfig()
    return feeder_config


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.logger = Logger(gc.debug_level)
    gc.timeouts = mkTimeouts()
    gc.default_motor_speeds = mkDefaultMotorSpeeds()
    gc.feeder_config = mkFeederConfig()
    gc.classification_chamber_vision_model_path = "/Users/spencer/code/yolo-trainer/runs/segment/checkpoints/run_1769112999_640_small_100epochs_20batch_data/weights/best.pt"
    gc.feeder_vision_model_path = "/Users/spencer/code/yolo-trainer/runs/segment/checkpoints/run_1769111277_640_small_100epochs_20batch_data/weights/best.pt"
    return gc
