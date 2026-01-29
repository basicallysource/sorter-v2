import os
from logger import Logger


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        self.main_loop_sleep_ms = 10
        self.heartbeat_interval_ms = 5000


class FeederConfig:
    def __init__(self):
        pass


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts
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


def mkFeederConfig() -> FeederConfig:
    feeder_config = FeederConfig()
    return feeder_config


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.logger = Logger(gc.debug_level)
    gc.timeouts = mkTimeouts()
    gc.feeder_config = mkFeederConfig()
    gc.classification_chamber_vision_model_path = "/Users/spencer/code/yolo-trainer/runs/segment/checkpoints/run_1769112999_640_small_100epochs_20batch_data/weights/best.pt"
    gc.feeder_vision_model_path = "/Users/spencer/code/yolo-trainer/runs/segment/checkpoints/run_1769111277_640_small_100epochs_20batch_data/weights/best.pt"
    return gc
