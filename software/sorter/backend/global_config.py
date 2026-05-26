from __future__ import annotations
import os
import sys
import argparse
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from logger import Logger
from profiler import Profiler
from blob_manager import getMachineId

if TYPE_CHECKING:
    from run_recorder import RunRecorder
    from runtime_stats import RuntimeStatsCollector


class RegionProviderType(Enum):
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
    use_channel_bus: bool
    disable_video_streams: list[str]  # "feeder", "classification_bottom", "classification_top"
    run_recorder: "RunRecorder"
    runtime_stats: "RuntimeStatsCollector"
    brickognize_dump_images: bool
    def __init__(self):
        from runtime_stats import RuntimeStatsCollector

        self.debug_level = 0
        self.should_write_camera_feeds = False
        self.brickognize_dump_images = False
        self.disable_chute = False
        # On the restart branch we explicitly simulate the distributor: the
        # Waveshare layer-servo bus isn't reliably available, but C1-C4 must
        # still run continuously. ``disable_servos=True`` makes the
        # Positioning state machine fall through without waiting on real
        # layer-servo motion. Override with ``--disable servos`` (still
        # honored) or LEGOSORTER_DISABLE env, or flip back here once the
        # layer-servo bus is reattached.
        self.disable_servos = True
        self.rotary_channel_steppers_can_operate_in_parallel = False
        self.use_channel_bus = False
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
    # Allow env-var fallback so the launching supervisor can flip these
    # without needing to thread CLI args through to a child main.py — useful
    # in distributor-simulated configurations where the layer-servo Waveshare
    # bus isn't fully wired yet but C1-C4 should still run continuously.
    env_disable = {
        token.strip()
        for token in os.getenv("LEGOSORTER_DISABLE", "").split(",")
        if token.strip()
    }
    gc.disable_chute = "chute" in args.disable or "chute" in env_disable
    gc.disable_servos = "servos" in args.disable or "servos" in env_disable
    gc.use_channel_bus = os.getenv("USE_CHANNEL_BUS", "0") == "1"
    gc.brickognize_dump_images = os.getenv("BRICKOGNIZE_DUMP_IMAGES", "0") == "1"
    gc.region_provider = RegionProviderType.HANDDRAWN

    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log")
    gc.logger = Logger(gc.debug_level, log_file=log_file)
    gc.profiler = Profiler(
        enabled=os.getenv("PROFILER_ENABLED", "1") == "1",
        report_interval_s=float(os.getenv("PROFILER_REPORT_INTERVAL_S", "5")),
    )

    return gc
