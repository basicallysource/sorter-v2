import os
import sys
import argparse
import uuid
from logger import Logger
from blob_manager import getMachineId


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        self.main_loop_sleep_ms = 10
        self.heartbeat_interval_ms = 5000


class RotorPulseConfig:
    steps_per_pulse: int
    delay_us: int
    accel_start_delay_us: int
    accel_steps: int
    decel_steps: int
    delay_between_pulse_ms: int

    def __init__(
        self,
        steps: int,
        delay_us: int,
        delay_between_ms: int,
        accel_start_delay_us: int | None = None,
        accel_steps: int = 0,
        decel_steps: int | None = None,
    ):
        self.steps_per_pulse = steps
        self.delay_us = delay_us
        self.accel_start_delay_us = (
            delay_us if accel_start_delay_us is None else accel_start_delay_us
        )
        self.accel_steps = accel_steps
        self.decel_steps = accel_steps if decel_steps is None else decel_steps
        self.delay_between_pulse_ms = delay_between_ms


class FeederConfig:
    first_rotor: RotorPulseConfig
    second_rotor_normal: RotorPulseConfig
    second_rotor_precision: RotorPulseConfig
    third_rotor_normal: RotorPulseConfig
    third_rotor_precision: RotorPulseConfig
    third_channel_dropzone_threshold_px: int
    second_channel_dropzone_threshold_px: int
    object_channel_overlap_threshold: float

    def __init__(self):
        self.first_rotor = RotorPulseConfig(
            steps=100,
            delay_us=500,
            delay_between_ms=5000,
            accel_start_delay_us=900,
            accel_steps=48,
            decel_steps=48,
        )
        self.second_rotor_normal = RotorPulseConfig(
            steps=500,
            delay_us=200,
            delay_between_ms=250,
            accel_start_delay_us=1200,
            accel_steps=130,
            decel_steps=130,
        )
        self.second_rotor_precision = RotorPulseConfig(
            steps=100,
            delay_us=800,
            delay_between_ms=350,
            accel_start_delay_us=1400,
            accel_steps=26,
            decel_steps=26,
        )
        self.third_rotor_normal = RotorPulseConfig(
            steps=1000,
            delay_us=200,
            delay_between_ms=250,
            accel_start_delay_us=1400,
            accel_steps=220,
            decel_steps=220,
        )
        self.third_rotor_precision = RotorPulseConfig(
            steps=100,
            delay_us=800,
            delay_between_ms=350,
            accel_start_delay_us=1400,
            accel_steps=26,
            decel_steps=26,
        )
        self.third_channel_dropzone_threshold_px = 350
        self.second_channel_dropzone_threshold_px = 500
        self.object_channel_overlap_threshold = 0.15


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
    machine_id: str
    run_id: str
    should_profile_feeder: bool
    telemetry_enabled: bool
    telemetry_url: str
    log_buffer_size: int
    disable_chute: bool

    def __init__(self):
        self.debug_level = 0
        self.vision_mask_proximity_threshold = 0.5
        self.should_write_camera_feeds = False
        self.should_profile_feeder = False
        self.log_buffer_size = 100
        self.disable_chute = False


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


def mkFeederConfig() -> FeederConfig:
    feeder_config = FeederConfig()
    return feeder_config


def mkGlobalConfig() -> GlobalConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--disable",
        action="append",
        default=[],
        help="disable subsystems (e.g., --disable chute)",
    )
    args = parser.parse_args()

    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.log_buffer_size = int(os.getenv("LOG_BUFFER_SIZE", "100"))
    gc.timeouts = mkTimeouts()
    gc.feeder_config = mkFeederConfig()
    gc.classification_chamber_vision_model_path = os.environ[
        "CLASSIFICATION_CHAMBER_MODEL_PATH"
    ]
    gc.feeder_vision_model_path = os.environ["FEEDER_MODEL_PATH"]
    gc.parts_with_categories_file_path = os.environ["PARTS_WITH_CATEGORIES_FILE_PATH"]
    gc.machine_id = getMachineId()
    gc.run_id = str(uuid.uuid4())
    gc.telemetry_enabled = os.getenv("TELEMETRY_ENABLED", "0") == "1"
    gc.telemetry_url = os.getenv("TELEMETRY_URL", "https://api.basically.website")

    gc.disable_chute = "chute" in args.disable

    from telemetry import Telemetry

    telemetry = Telemetry(gc)
    gc.logger = Logger(gc.debug_level, gc.log_buffer_size, telemetry.uploadLogs)

    return gc
