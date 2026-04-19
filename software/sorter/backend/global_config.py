from __future__ import annotations
import os
import sys
import argparse
import uuid
from enum import Enum
from typing import TYPE_CHECKING
from logger import Logger
from profiler import Profiler
from blob_manager import getMachineId

if TYPE_CHECKING:
    from run_recorder import RunRecorder
    from runtime_stats import RuntimeStatsCollector


class RegionProviderType(Enum):
    ARUCO = "aruco"
    HANDDRAWN = "handdrawn"


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        from defs.consts import LOOP_TICK_MS
        self.main_loop_sleep_ms = LOOP_TICK_MS
        self.heartbeat_interval_ms = 5000


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts
    sorting_profile_path: str
    should_write_camera_feeds: bool
    machine_id: str
    run_id: str
    disable_chute: bool
    disable_servos: bool
    region_provider: RegionProviderType
    profiler: Profiler
    rotary_channel_steppers_can_operate_in_parallel: bool
    disable_video_streams: list[str]  # "feeder", "classification_bottom", "classification_top"
    run_recorder: "RunRecorder"
    runtime_stats: "RuntimeStatsCollector"
    def __init__(self):
        from runtime_stats import RuntimeStatsCollector

        self.debug_level = 0
        self.should_write_camera_feeds = False
        self.disable_chute = False
        self.disable_servos = False
        self.rotary_channel_steppers_can_operate_in_parallel = False
        self.disable_video_streams = ["classification_bottom"]
        self.runtime_stats = RuntimeStatsCollector()


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


def mkGlobalConfig() -> GlobalConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--disable",
        action="append",
        default=[],
        help="disable subsystems (e.g., --disable chute, --disable servos)",
    )
    args = parser.parse_args()

    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.timeouts = mkTimeouts()
    gc.sorting_profile_path = os.environ["SORTING_PROFILE_PATH"]
    gc.machine_id = getMachineId()
    gc.run_id = str(uuid.uuid4())
    gc.disable_chute = "chute" in args.disable
    gc.disable_servos = "servos" in args.disable
    gc.region_provider = RegionProviderType.HANDDRAWN

    gc.logger = Logger(gc.debug_level)
    gc.profiler = Profiler(
        enabled=os.getenv("PROFILER_ENABLED", "0") == "1",
        report_interval_s=float(os.getenv("PROFILER_REPORT_INTERVAL_S", "5")),
    )

    return gc
