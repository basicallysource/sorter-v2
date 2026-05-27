from __future__ import annotations
import os
import sys
import argparse
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, TYPE_CHECKING
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
    disable_c_channels: set[int]  # {1, 2, 3, 4} — c-channel rotor steppers to suppress
    disable_carousel: bool         # carousel stepper (same physical motor as c_channel_4)
    no_power_development_mode: bool
    region_provider: RegionProviderType
    profiler: Profiler
    rotary_channel_steppers_can_operate_in_parallel: bool
    use_channel_bus: bool
    # Rev03 producer/slot architecture: when True, dedicated per-camera
    # producer threads own inference; preview overlays and the coordinator
    # read latest-detection slots instead of triggering inference. Gates the
    # aux detection pool, preview-driven inference, and the coordinator's
    # inline-carousel leak off. Old paths (heatmap, dynamic tracking with
    # gemini, mog2) still work when the role's algorithm isn't a local model.
    use_new_vision: bool
    disable_video_streams: list[str]  # "feeder", "classification_bottom", "classification_top"
    run_recorder: "RunRecorder"
    runtime_stats: "RuntimeStatsCollector"
    brickognize_dump_root: Optional[Path]
    classification_burst_dump_root: Optional[Path]
    def __init__(self):
        from runtime_stats import RuntimeStatsCollector

        self.debug_level = 0
        self.should_write_camera_feeds = False
        self.brickognize_dump_root: Optional[Path] = None
        self.classification_burst_dump_root: Optional[Path] = None
        self.disable_chute = False
        # On the restart branch we explicitly simulate the distributor: the
        # Waveshare layer-servo bus isn't reliably available, but C1-C4 must
        # still run continuously. ``disable_servos=True`` makes the
        # Positioning state machine fall through without waiting on real
        # layer-servo motion. Override with ``--disable servos`` (still
        # honored) or LEGOSORTER_DISABLE env, or flip back here once the
        # layer-servo bus is reattached.
        self.disable_servos = True
        self.disable_c_channels: set[int] = set()
        self.disable_carousel = False
        self.no_power_development_mode = False
        self.rotary_channel_steppers_can_operate_in_parallel = False
        self.use_channel_bus = False
        self.use_new_vision = False
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
    all_disable = set(args.disable) | env_disable
    gc.disable_chute = "chute" in all_disable
    gc.disable_servos = "servos" in all_disable
    for ch in (1, 2, 3, 4):
        if f"c_channel_{ch}" in all_disable:
            gc.disable_c_channels.add(ch)
    gc.disable_carousel = "carousel" in all_disable
    gc.no_power_development_mode = os.getenv("NO_POWER_DEVELOPMENT_MODE", "0") == "1"
    if gc.no_power_development_mode:
        gc.disable_chute = True
        gc.disable_servos = True
    gc.use_channel_bus = os.getenv("USE_CHANNEL_BUS", "0") == "1"
    gc.use_new_vision = os.getenv("USE_NEW_VISION", "0") == "1"
    gc.region_provider = RegionProviderType.HANDDRAWN

    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    if os.getenv("BRICKOGNIZE_DUMP_IMAGES", "0") == "1":
        gc.brickognize_dump_root = Path(log_dir).resolve() / "brickognize" / gc.run_id
    if os.getenv("CLASSIFICATION_BURST_DUMP_IMAGES", "0") == "1":
        gc.classification_burst_dump_root = Path(log_dir).resolve() / "classification_burst" / gc.run_id
    log_file = os.path.join(log_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log")
    gc.logger = Logger(gc.debug_level, log_file=log_file)
    gc.profiler = Profiler(
        enabled=os.getenv("PROFILER_ENABLED", "1") == "1",
        report_interval_s=float(os.getenv("PROFILER_REPORT_INTERVAL_S", "5")),
    )

    return gc
