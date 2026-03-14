import os
import sys
import argparse
import uuid
from enum import Enum
from logger import Logger
from profiler import Profiler
from blob_manager import getMachineId


class RegionProviderType(Enum):
    ARUCO = "aruco"
    HANDDRAWN = "handdrawn"


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        self.main_loop_sleep_ms = 10
        self.heartbeat_interval_ms = 5000


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts
    parts_with_categories_file_path: str
    should_write_camera_feeds: bool
    machine_id: str
    run_id: str
    telemetry_enabled: bool
    telemetry_url: str
    log_buffer_size: int
    disable_chute: bool
    region_provider: RegionProviderType
    profiler: Profiler
    rotary_channel_steppers_can_operate_in_parallel: bool
    disable_video_streams: list[str]  # "feeder", "classification_bottom", "classification_top"

    def __init__(self):
        self.debug_level = 0
        self.should_write_camera_feeds = False
        self.log_buffer_size = 100
        self.disable_chute = False
        self.rotary_channel_steppers_can_operate_in_parallel = False
        self.disable_video_streams = ["classification_bottom"]


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


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
    gc.parts_with_categories_file_path = os.environ["PARTS_WITH_CATEGORIES_FILE_PATH"]
    gc.machine_id = getMachineId()
    gc.run_id = str(uuid.uuid4())
    gc.telemetry_enabled = os.getenv("TELEMETRY_ENABLED", "0") == "1"
    gc.telemetry_url = os.getenv("TELEMETRY_URL", "https://api.basically.website")

    gc.disable_chute = "chute" in args.disable
    gc.region_provider = RegionProviderType.HANDDRAWN

    from telemetry import Telemetry

    telemetry = Telemetry(gc)
    gc.logger = Logger(gc.debug_level, gc.log_buffer_size, telemetry.uploadLogs)
    gc.profiler = Profiler(
        enabled=os.getenv("PROFILER_ENABLED", "0") == "1",
        report_interval_s=float(os.getenv("PROFILER_REPORT_INTERVAL_S", "5")),
    )

    return gc
